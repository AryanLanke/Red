"""Add a companion look from any VRM file: copy it into RED_HOME, render every frame, finish them.

    python scripts\\avatar_render\\add.py C:\\Users\\you\\Downloads\\model.vrm bruno --name Bruno --voice am_fenrir

Run it from PowerShell (headless Edge exits silently under Git Bash). Needs Node and, once,
`npm install --ignore-scripts` in this folder. The VRM goes to RED_HOME\\config\\companion\\<id>.vrm and
the frames to RED_HOME\\models\\companion\\<id>\\; the companion then shows in the companion's right-click
menu and can be picked with RED_COMPANION=<id>. Check the model's licence first: VRoid Hub shows it on
the model's page, and a VRM file carries it too (this script prints it).
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import struct
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

from red.config import load_settings  # noqa: E402


def vrm_meta(path: Path) -> dict:
    """The model's title, author and licence fields, read from the file's header."""
    with open(path, "rb") as f:
        magic, _, _ = struct.unpack("<4sII", f.read(12))
        if magic != b"glTF":
            raise SystemExit(f"{path} isn't a VRM (glTF binary) file")
        length, _ = struct.unpack("<II", f.read(8))
        data = json.loads(f.read(length))
    ext = data.get("extensions", {})
    if "VRM" in ext:
        return {"version": "0.0", **ext["VRM"].get("meta", {})}
    if "VRMC_vrm" in ext:
        return {"version": "1.0", **ext["VRMC_vrm"].get("meta", {})}
    raise SystemExit(f"{path} is a glTF file but not a VRM avatar")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("vrm", type=Path)
    ap.add_argument("id", help="a short lowercase id, like bruno")
    ap.add_argument("--name", help="the name shown in the menu (default: the id, capitalised)")
    ap.add_argument("--voice", help="Kokoro voice for its pickup clips, like am_fenrir")
    args = ap.parse_args()
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", args.id):
        raise SystemExit("the id must be lowercase letters, digits, - or _ (like bruno)")

    meta = vrm_meta(args.vrm)
    print(f"Model: {meta.get('title') or meta.get('name')} by {meta.get('author') or meta.get('authors')}"
          f" (VRM {meta['version']})")
    for key in ("licenseName", "otherPermissionUrl", "commercialUssageName", "allowedUserName",
                "avatarPermission", "commercialUsage", "modification", "allowRedistribution", "creditNotation"):
        if meta.get(key):
            print(f"  {key}: {meta[key]}")

    settings = load_settings()
    stored = settings.home / "config" / "companion" / f"{args.id}.vrm"
    stored.parent.mkdir(parents=True, exist_ok=True)
    if args.vrm.resolve() != stored.resolve():
        shutil.copyfile(args.vrm, stored)
    out = settings.models_dir / "companion" / args.id
    raw = out / "raw"
    if not (HERE / "node_modules").exists():
        subprocess.run(["npm", "install", "--ignore-scripts", "--no-audit", "--no-fund"], cwd=HERE,
                       check=True, shell=True)
    subprocess.run(["node", str(HERE / "render.mjs"), "--vrm", str(stored), "--out", str(raw)], cwd=HERE,
                   check=True)
    finish = [sys.executable, str(HERE / "finish.py"), str(raw), str(out),
              "--name", args.name or args.id.title()]
    if args.voice:
        finish += ["--voice", args.voice]
    subprocess.run(finish, check=True)
    print(f"Done: {out}. Look at sheet-peek.png, sheet-cornerR.png and sheet-body.png there.")


if __name__ == "__main__":
    main()
