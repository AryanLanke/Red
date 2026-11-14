"""Rank the measured Freesound candidates for each reaction kind and print the best few (dev tool).

    python scripts/sound_shortlist.py D:\\RED\\cache\\sound-work [--kind giggle] [--top 10]

Reads cands.json (scripts/sound_search.py) and meas.json (scripts/sound_measure.py). A clip scores
for keywords of the kind in its title and tags (and description), for sounding young and cute, and
for being clean and short; it is dropped for child/baby/crowd/horror words and for being too quiet
or clipped. Gender comes from the words, else from the pitch (under 165 Hz a man, over 190 a woman).
Nobody has listened to these: the user's ears are the last check.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

KEYWORDS = {
    "pickup": ["gasp", "whoa", "wow", "surprise", "surprised", "eek", "yelp", "hey", "oh", "wah", "squeal"],
    "drop": ["ow", "ouch", "oof", "pain", "hurt", "umph", "oww", "ugh", "bump", "thud"],
    "hover": ["hm", "hmm", "hmm?", "huh", "curious", "oh", "ooh", "interested", "question", "eh"],
    "surprised": ["gasp", "surprise", "surprised", "shock", "shocked", "what", "huh", "oh", "wow"],
    "laugh": ["laugh", "laughter", "laughing", "haha", "chuckle"],
    "giggle": ["giggle", "giggles", "giggling", "chuckle", "titter", "snicker"],
    "sigh": ["sigh", "exhale", "relief", "phew", "relieved"],
    "yawn": ["yawn", "yawning"],
    "hmm": ["hmm", "hm", "mhm", "thinking", "ponder", "thoughtful", "uh", "um"],
    "annoyed": ["hmph", "annoyed", "ugh", "groan", "grumble", "tsk", "huff", "irritated", "scoff", "grunt", "pout"],
    "happy": ["yay", "woohoo", "cheer", "hooray", "excited", "wee", "yippee", "yes", "woo", "happy", "celebrate"],
    "sleepy": ["yawn", "sleepy", "tired", "mumble", "drowsy", "sleep", "snore"],
    "poke": ["squeak", "eep", "yelp", "squeal", "ticklish", "eek", "tickle", "squeaky", "ah"],
    "drag_fast": ["hey", "whoa", "wah", "waah", "wow", "wee", "no", "stop", "aah", "yell"],
    "dizzy": ["dizzy", "woozy", "whoa", "ooh", "groan", "wobble", "drunk", "confused", "ohh"],
    "pout": ["hmph", "pout", "huff", "sulk", "tsk", "sigh", "mm", "sad", "whine"],
    "sneeze": ["sneeze", "achoo", "sneezing"],
    "hiccup": ["hiccup", "hiccups", "hic"],
    "climb": ["effort", "grunt", "hup", "heave", "exertion", "lift", "hnn", "pull", "strain", "ugh", "up", "jump"],
    "zip": ["zip", "zipper", "zip-up", "unzip"],
}
NICE = {"cute", "anime", "kawaii", "young", "teen", "teenage", "girly", "playful", "happy", "funny", "cartoon",
        "character-voice", "game", "short", "girl", "boy", "squeaky"}
REJECT = re.compile(r"\b(child|children|kid|kids|baby|babies|toddler|infant|little girl|little boy|daughter|son|"
                    r"nephew|niece|crowd|audience|group|people|scream|screaming|horror|monster|zombie|demon|"
                    r"creepy|robot|alien|creature|orc|dragon|death|dying|sensual|moan|moaning|sex|erotic|"
                    r"orgasm|whimper|ghost|evil|witch|villain|old man|old woman|elderly|grandma|grandpa|"
                    r"choking|vomit|cough|gore|blood|scary|cry|crying|sob|sobbing|weep|porn|porno|nsfw|sexy|fangasm|yaoi|"
                    r"hentai|lewd|fetish|bdsm|kiss|kissing|naked|strip|fart|farting)\b")
FEMALE = re.compile(r"\b(female|woman|women|girl|girls|lady|she|her|feminine|girly)\b")
MALE = re.compile(r"\b(male|man|men|guy|boy|he|his|masculine|dude)\b")


def gender(text: str, f0: float) -> str:
    f, m = bool(FEMALE.search(text)), bool(MALE.search(text))
    if f and not m:
        return "female"
    if m and not f:
        return "male"
    if f0 and f0 < 165:
        return "male"
    if f0 and f0 > 190:
        return "female"
    return "?"


def score(kind: str, c: dict, m: dict) -> float:
    title = c["title"].lower()
    tags = [t.lower() for t in c["tags"]]
    desc = c["description"].lower()
    words = set(re.findall(r"[a-z]+", title)) | set(tags)
    s = 0.0
    for k in KEYWORDS[kind]:
        if k in words:
            s += 3 if k == KEYWORDS[kind][0] else 2
        elif re.search(rf"\b{re.escape(k)}\b", desc):
            s += 0.7
    s += 0.5 * len(NICE & words)
    s += math.log10(1 + c.get("downloads", 0)) * 0.4
    if m["rms_db"] < -36:
        s -= 3
    if m["peak_db"] > -0.5:
        s -= 2
    if m["secs"] > 2.0:
        s -= 1.5
    if m["secs"] < 0.15:
        s -= 3
    return s


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("work")
    p.add_argument("--kind", nargs="*")
    p.add_argument("--top", type=int, default=10)
    p.add_argument("--json", help="write the ranked lists here")
    args = p.parse_args()
    work = Path(args.work)
    cands = json.loads((work / "cands.json").read_text(encoding="utf-8"))
    meas = json.loads((work / "meas.json").read_text(encoding="utf-8"))
    out = {}
    for kind in args.kind or KEYWORDS:
        rows = {"female": [], "male": [], "?": []}
        for sid, c in cands.items():
            m = meas.get(sid) or {}
            if "secs" not in m:
                continue
            text = " ".join([c["title"], " ".join(c["tags"]), c["description"]]).lower()
            if REJECT.search(text):
                continue
            sc = score(kind, c, m)
            if sc < 2.5:
                continue
            rows[gender(text, m["f0"])].append((sc, sid, c, m))
        out[kind] = {}
        for g in ("female", "male", "?"):
            rows[g].sort(key=lambda r: -r[0])
            out[kind][g] = [r[1] for r in rows[g][: args.top]]
            print(f"=== {kind} / {g} ({len(rows[g])} fit)")
            for sc, sid, c, m in rows[g][: args.top]:
                print(f"{sid:>7} {c['license_key']:4s} {sc:4.1f} {m['secs']:.1f}s f0={m['f0']:3d} rms={m['rms_db']:.0f} | "
                      f"{c['title'][:30]} | {','.join(c['tags'][:4])} | {c['user']}")
    if args.json:
        Path(args.json).write_text(json.dumps(out, indent=1), encoding="utf-8")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    main()
