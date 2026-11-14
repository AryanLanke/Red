"""Find licensed reaction clips on Freesound (a dev tool: it writes a candidate list, never audio into git).

    python scripts/sound_search.py "giggle girl" "squeal" --out cache\\sound-candidates.json

Freesound's search page works without an account: each result carries the id, author, duration, tags,
the description and a preview URL. Only CC0 and CC-BY sounds are asked for (never the NonCommercial
ones); the licence is checked again on each sound's own page by `scripts/make_sounds.py` before a clip
goes in a pack. If RED_HOME\\config\\secrets holds a Freesound key (red.secrets), the API is not needed
for this: the website's preview files are what Red uses.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36")
LICENSES = {"cc0": 'license:"Creative Commons 0"', "by": 'license:"Attribution"'}
MAX_SECONDS = 2.5


def fetch(url: str, *, binary: bool = False, tries: int = 3, pause: float = 0.4):
    last: Exception | None = None
    for n in range(tries):
        try:
            time.sleep(pause)
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            data = urllib.request.urlopen(req, timeout=40).read()
            return data if binary else data.decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 * (n + 1))
    raise RuntimeError(f"{url}: {last}")


def _attr(block: str, name: str) -> str:
    m = re.search(rf'data-{name}="([^"]*)"', block)
    return html.unescape(m.group(1)) if m else ""


def parse_results(page: str) -> list[dict]:
    """The sounds on a Freesound search page."""
    out = []
    for block in page.split('aria-label="Sound ')[1:]:
        sid = _attr(block, "sound-id")
        user = _attr(block, "username")
        if not sid or not user:
            continue
        desc = re.search(r'<div class="max-h-60px[^>]*>\s*(.*?)\s*</div>', block, re.S)
        tags = re.findall(r'href="/browse/tags/([^/"]+)/"', block)
        out.append({
            "id": int(sid), "user": user, "title": _attr(block, "title"),
            "duration": float(_attr(block, "duration") or 0),
            "mp3": _attr(block, "mp3"), "ogg": _attr(block, "ogg"),
            "downloads": int(_attr(block, "num-downloads") or 0),
            "description": " ".join(re.sub(r"<[^>]+>", " ", html.unescape(desc.group(1))).split()) if desc else "",
            "tags": tags,
            "page": f"https://freesound.org/people/{user}/sounds/{sid}/",
        })
    return out


def search(query: str, license_key: str, *, pages: int = 1, max_seconds: float = MAX_SECONDS,
           user: str = "") -> list[dict]:
    found = []
    for page in range(1, pages + 1):
        f = f"{LICENSES[license_key]} duration:[0 TO {max_seconds}]"
        if user:
            f += f' username:"{user}"'
        url = "https://freesound.org/search/?" + urllib.parse.urlencode(
            {"q": query, "f": f, "s": "downloads desc", "page": page})
        try:
            rows = parse_results(fetch(url))
        except RuntimeError as e:
            print("  search failed:", e, file=sys.stderr)
            break
        for r in rows:
            r["query"], r["license_key"] = query, license_key
        found += rows
        if len(rows) < 10:
            break
    return found


def licence_of(page_url: str) -> tuple[str, str]:
    """(licence name, licence URL) from the sound's own page: the check before a clip is used."""
    page = fetch(page_url)
    m = re.search(r'href="(https?://creativecommons\.org/(?:licenses|publicdomain)/[^"]+)"', page)
    if not m:
        return "", ""
    url = m.group(1)
    if "publicdomain/zero" in url:
        return "CC0 1.0", url
    kind = re.search(r"/licenses/([a-z\-]+)/([0-9.]+)", url)
    name = f"CC {kind.group(1).upper()} {kind.group(2)}" if kind else "CC"
    return name, url


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("queries", nargs="*", help="none with --user: all of that user's short sounds")
    p.add_argument("--out", required=True)
    p.add_argument("--pages", type=int, default=1)
    p.add_argument("--max-seconds", type=float, default=MAX_SECONDS)
    p.add_argument("--user", help="only this Freesound user's sounds (queries then narrow within them)")
    args = p.parse_args()
    out = Path(args.out)
    db = json.loads(out.read_text(encoding="utf-8")) if out.is_file() else {}
    for q in args.queries or ([""] if args.user else []):
        for lic in LICENSES:
            rows = search(q, lic, pages=args.pages, max_seconds=args.max_seconds, user=args.user or "")
            for r in rows:
                old = db.get(str(r["id"]))
                if old:
                    old.setdefault("queries", [])
                    if q not in old["queries"]:
                        old["queries"].append(q)
                else:
                    r["queries"] = [q]
                    db[str(r["id"])] = r
            print(f"{q!r} {lic}: {len(rows)}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(db, indent=1, ensure_ascii=False), encoding="utf-8")
    print(len(db), "candidates in", out)


if __name__ == "__main__":
    main()
