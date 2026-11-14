"""Choose which licensed clip goes in which pack and kind, and write sounds/sources.toml (dev tool).

    python scripts/sound_assign.py D:\\RED\\cache\\sound-work [--write] [--veto 123 456]

Takes the ranked candidates of scripts/sound_shortlist.py, keeps the best few per kind and gender
with different authors where it can, checks each chosen clip's licence on its own Freesound page
(only CC0 and CC-BY pass), and shares them out: en-female-1/2 and jp-female-1/2 from the women's
list, en-male-1 and jp-male-1/2 from the men's. A veto list (ids heard to be wrong) comes from
sounds/vetoes.txt. Nobody listened to the ranking: the user's ears are the last check, and the
report says so.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from sound_search import fetch, licence_of  # noqa: E402
from sound_shortlist import KEYWORDS, REJECT, gender, score  # noqa: E402

KINDS = tuple(KEYWORDS)
UNISEX = {"zip"}                                # a zipper has no gender
MAYBE_UNSEXED = {"sneeze", "hiccup"}            # a sneeze or a hiccup with no pitch may go to either
FEMALE_PACKS = ("en-female-1", "en-female-2", "jp-female-1", "jp-female-2")
MALE_PACKS = ("en-male-1", "jp-male-1", "jp-male-2")
# What only makes sense in English words: a Japanese pack falls back to Kokoro's Japanese for these
# unless the clip is tagged Japanese or anime.
ENGLISH_ONLY = {"drop", "hover", "drag_fast", "happy", "climb"}
VOICE_LIKE = re.compile(r"\b(voice|vocal|human|female|male|girl|man|woman|boy|guy|lady|speak|speech|"
                        r"character|anime|cute|person|mouth|breath|breathing|english|japanese|teen)\b")
NOT_A_VOICE = re.compile(r"\b(door|creak|creaking|metal|truck|tube|plastic|balloon|wooden|machine|piano|"
                         r"drum|animal|dog|cat|bird|rat|mouse|chair|floor|hinge|rusty|squeaky toy|toy)\b")
ANIME = re.compile(r"\b(anime|japanese|kawaii|cartoon|character-voice|cute)\b")
PER_PACK = 3
MAX_EFFECTIVE = 1.5


def effective(m: dict) -> float:
    return m["secs"] - m["head_s"] - m["tail_s"]


def ranked(kind: str, who: str, cands: dict, meas: dict, veto: set[str]) -> list[str]:
    """Best-first ids for a kind and gender, at most two per author in a row of results."""
    rows = []
    for sid, c in cands.items():
        m = meas.get(sid) or {}
        if "secs" not in m or sid in veto:
            continue
        text = " ".join([c["title"], " ".join(c["tags"]), c["description"]]).lower()
        if REJECT.search(text):
            continue
        g = gender(text, m["f0"])
        if kind in UNISEX:
            pass
        elif g != who and not (g == "?" and kind in MAYBE_UNSEXED and m["f0"] == 0):
            continue
        words = set(re.findall(r"[a-z]+", c["title"].lower())) | {x.lower() for x in c["tags"]}
        if kind not in UNISEX:
            if not (set(KEYWORDS[kind]) & words):          # the kind must be in the title or the tags
                continue
            if not VOICE_LIKE.search(text) or NOT_A_VOICE.search(text):
                continue
        sc = score(kind, c, m)
        eff = effective(m)
        if eff > MAX_EFFECTIVE:
            sc -= 2.5 * (eff - MAX_EFFECTIVE)
        if sc < 3.0:
            continue
        rows.append((sc, sid))
    rows.sort(key=lambda r: -r[0])
    out, per_author = [], Counter()
    for sc, sid in rows:
        a = cands[sid]["user"]
        if per_author[a] >= 2:
            continue
        per_author[a] += 1
        out.append(sid)
    return out


def anime_first(ids: list[str], cands: dict) -> list[str]:
    def key(sid):
        c = cands[sid]
        text = " ".join([c["title"], " ".join(c["tags"]), c["description"]]).lower()
        return 0 if ANIME.search(text) else 1
    return sorted(ids, key=key)        # stable: the ranking stays within each group


def orders(kind: str, who: str, ids: list[str], cands: dict) -> dict[str, list[str]]:
    """pack -> its preferred ids, best first. The two packs of a language take the odd and the even ranks."""
    def rotate(pool, k):
        return pool[k::2] + pool[(k + 1) % 2::2]
    if who == "female":
        jp = anime_first(ids, cands) if kind not in ENGLISH_ONLY else []
        return {"en-female-1": rotate(ids, 0), "en-female-2": rotate(ids, 1),
                "jp-female-1": jp, "jp-female-2": jp[PER_PACK:] + jp[:PER_PACK]}
    jp = ids if kind not in ENGLISH_ONLY else []
    return {"en-male-1": ids, "jp-male-1": jp, "jp-male-2": jp[PER_PACK:] + jp[:PER_PACK]}


def toml_str(s: str) -> str:
    s = " ".join(s.split())
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("work")
    p.add_argument("--write", action="store_true")
    p.add_argument("--veto", nargs="*", default=[])
    args = p.parse_args()
    work = Path(args.work)
    cands = json.loads((work / "cands.json").read_text(encoding="utf-8"))
    meas = json.loads((work / "meas.json").read_text(encoding="utf-8"))
    vetoes_file = ROOT / "sounds" / "vetoes.txt"
    veto = set(args.veto)
    if vetoes_file.is_file():
        veto |= {ln.split("#")[0].strip() for ln in vetoes_file.read_text(encoding="utf-8").splitlines() if ln.split("#")[0].strip()}

    plan: dict[tuple[str, str], list[str]] = {}         # (pack, kind) -> ids
    used: dict[str, set[str]] = {}                       # pack -> ids already used for some kind
    pools = {(kind, who): ranked(kind, who, cands, meas, veto)
             for kind in KINDS if kind not in UNISEX for who in ("female", "male")}
    for (kind, who), ids in sorted(pools.items(), key=lambda kv: len(kv[1])):    # scarcest first
        for pack, order in orders(kind, who, ids, cands).items():
            skip = set() if kind == "sleepy" else used.setdefault(pack, set())    # a sleepy sound is a yawn
            taken = [sid for sid in order if sid not in skip][:PER_PACK]
            if taken:
                plan[(pack, kind)] = taken
                used.setdefault(pack, set()).update(taken)
    for kind in KINDS:
        if kind in UNISEX:
            ids = ranked(kind, "female", cands, meas, veto)
            for i, pack in enumerate(FEMALE_PACKS + MALE_PACKS):
                plan[(pack, kind)] = [ids[(i + k) % len(ids)] for k in range(min(2, len(ids)))] if ids else []
    chosen = sorted({sid for ids in plan.values() for sid in ids})
    print(len(chosen), "clips chosen; checking licences and hashes...")

    def check(sid: str):
        c = cands[sid]
        name, url = licence_of(c["page"])
        data = fetch(c["mp3"].replace("-lq.", "-hq."), binary=True, pause=0.1)
        return sid, name, url, hashlib.sha256(data).hexdigest(), c["mp3"].replace("-lq.", "-hq.")
    with ThreadPoolExecutor(6) as ex:
        checked = {r[0]: r[1:] for r in ex.map(check, chosen)}

    ok, bad = {}, []
    for sid, (name, url, sha, dl) in checked.items():
        c = cands[sid]
        want_by = c["license_key"] == "by"
        good = (name == "CC0 1.0" and not want_by) or (name.startswith("CC BY ") and "NC" not in name and "ND" not in name and want_by)
        if name in ("CC BY 4.0", "CC BY 3.0", "CC0 1.0") and good:
            ok[sid] = (name, url, sha, dl)
        else:
            bad.append((sid, name))
    for sid, name in bad:
        print("  REJECTED licence:", sid, name or "(not found)", cands[sid]["page"])

    lines = ["# Licensed clips for the reaction packs (scripts/sound_assign.py; scripts/make_sounds.py builds from this).",
             "# No audio in git: each file is downloaded, its SHA-256 checked, trimmed and loudness-matched.",
             "# Only CC0 and CC-BY from Freesound.org. Credit lines are shown in the app (red.sounds.credits).", ""]
    for sid in sorted(ok, key=int):
        c = cands[sid]
        name, url, sha, dl = ok[sid]
        lines += ["[[source]]", f'id = "fs{sid}"', f"page = {toml_str(c['page'])}", f"url = {toml_str(dl)}",
                  f'sha256 = "{sha}"', f"author = {toml_str(c['user'])}", f"title = {toml_str(c['title'])}",
                  f'license = "{name}"', f"license_url = {toml_str(url)}", ""]
    for (pack, kind), ids in sorted(plan.items(), key=lambda kv: (kv[0][0], KINDS.index(kv[0][1]))):
        for sid in ids:
            if sid in ok:
                lines += ["[[use]]", f'source = "fs{sid}"', f'pack = "{pack}"', f'kind = "{kind}"', ""]
    text = "\n".join(lines)
    if args.write:
        (ROOT / "sounds").mkdir(exist_ok=True)
        (ROOT / "sounds" / "sources.toml").write_text(text, encoding="utf-8")
        print("wrote sounds/sources.toml:", len(ok), "sources")
    summary = {}
    for (pack, kind), ids in plan.items():
        summary.setdefault(pack, {})[kind] = [f"{sid}({cands[sid]['user']})" for sid in ids if sid in ok]
    for pack, kinds in sorted(summary.items()):
        print(f"\n## {pack}")
        for kind in KINDS:
            if kind in kinds:
                print(f"  {kind:10s} {', '.join(kinds[kind])}")
        missing = [k for k in KINDS if k not in kinds]
        print("  (no recorded clip -> Kokoro/made):", ", ".join(missing) or "none")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    main()
