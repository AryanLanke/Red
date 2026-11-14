"""Crops the raw renders from render.mjs, scales them and makes contact sheets.

    python scripts\\avatar_render\\finish.py D:\\RED\\models\\companion\\red\\raw D:\\RED\\models\\companion\\red

Frames come in sets (see frames.js): peek, the two bottom corners, top (hanging upside down), the two top corners (topL, topR) and body. Every frame of a set gets the same crop, so the character never
jumps between frames, and both sets are scaled to the same pixels per metre, so the character is the same
size when you pick it up. Peek frames are cut at the edge line: just under the forearms in `peek_idle`.
The window puts the bottom of a peek frame on the screen edge.

The output folder gets peek_*.png and body_*.png, frames.json (names, states, emotions, size, and where the
head and hands are on each picture) and sheet-peek.png / sheet-body.png to look at.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ALPHA_MIN = 8
PAD = 16
FOREARM = 0.05        # metres from the forearm bones to the underside of the sleeve


def union_box(images: list[Image.Image]) -> tuple[int, int, int, int]:
    boxes = [img.getchannel("A").point(lambda a: 255 if a > ALPHA_MIN else 0).getbbox() for img in images]
    boxes = [b for b in boxes if b]
    if not boxes:
        raise SystemExit("every frame is empty: the model did not render")
    w, h = images[0].size
    return (max(min(b[0] for b in boxes) - PAD, 0), max(min(b[1] for b in boxes) - PAD, 0),
            min(max(b[2] for b in boxes) + PAD, w), min(max(b[3] for b in boxes) + PAD, h))


def edge_line(entry: dict, upside_down: bool = False) -> int:
    """The y (raw pixels) just under the forearms of a peek frame (just over them when hanging)."""
    marks = entry["marks"]
    ys = [marks[k][1] for k in ("leftLowerArm", "rightLowerArm", "leftHand", "rightHand") if marks.get(k)]
    if upside_down:
        return round(min(ys) - FOREARM * entry["pxPerMetre"])
    return round(max(ys) + FOREARM * entry["pxPerMetre"])


def contact_sheet(frames: list[tuple[str, Image.Image]], path: Path, columns: int = 7, cell_h: int = 300) -> None:
    widest = max(img.width / img.height for _, img in frames)
    cell_w = int(cell_h * widest)
    label_h = 26
    rows = (len(frames) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * cell_w, rows * (cell_h + label_h)), (236, 236, 240))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(size=16)
    for i, (name, img) in enumerate(frames):
        x = (i % columns) * cell_w
        y = (i // columns) * (cell_h + label_h)
        bg = (226, 226, 232) if (i // columns + i % columns) % 2 else (244, 244, 248)
        draw.rectangle([x, y, x + cell_w, y + cell_h], fill=bg)
        tw = round(img.width * cell_h / img.height)
        thumb = img.resize((tw, cell_h), Image.LANCZOS)
        sheet.paste(thumb, (x + (cell_w - tw) // 2, y), thumb)
        draw.text((x + 6, y + cell_h + 4), name, fill=(30, 30, 40), font=font)
    sheet.save(path)


def finish_set(name: str, entries: list[dict], raw: Path, out: Path, ppm: float) -> dict:
    images = [Image.open(raw / f"{e['name']}.png").convert("RGBA") for e in entries]
    left, top, right, bottom = union_box(images)
    if name in ("peek", "cornerR", "cornerL", "top", "topL", "topR"):
        idle = next((e for e in entries if e["name"] == f"{name}_idle"), entries[0])
        if name.startswith("top"):
            top = edge_line(idle, upside_down=True)   # the window puts the top of these on the top edge
        else:
            bottom = edge_line(idle)
    # Corners: the side edge runs through the wrist of the hand gripping it, so only its fingers show.
    if name == "cornerR":
        right = idle["marks"]["leftHand"][0]
    elif name == "cornerL":
        left = idle["marks"]["rightHand"][0]
    elif name == "topL":                    # cornerR turned over: the left hand grips the left edge
        left = idle["marks"]["leftHand"][0]
    elif name == "topR":
        right = idle["marks"]["rightHand"][0]
    scale = ppm / entries[0]["pxPerMetre"]
    width, height = round((right - left) * scale), round((bottom - top) * scale)

    done, frames = [], []
    for entry, img in zip(entries, images):
        frame = img.crop((left, top, right, bottom)).resize((width, height), Image.LANCZOS)
        frame.save(out / f"{entry['name']}.png", optimize=True)
        done.append((entry["name"], frame))
        marks = {k: [round((v[0] - left) * scale), round((v[1] - top) * scale)]
                 for k, v in entry["marks"].items() if v}
        frames.append({"name": entry["name"], "state": entry["state"], "emotion": entry["emotion"], "marks": marks})
    contact_sheet(done, out / f"sheet-{name}.png")
    return {"size": [width, height], "frames": frames}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("raw", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--ppm", type=float, default=560, help="output pixels per metre (both sets)")
    ap.add_argument("--name", help="the companion's name, shown in its menu (default: the folder name)")
    ap.add_argument("--voice", help="the Kokoro voice for its pickup clips (default: Red's voice)")
    args = ap.parse_args()

    meta = json.loads((args.raw / "frames.json").read_text(encoding="utf-8"))
    args.out.mkdir(parents=True, exist_ok=True)
    old = args.out / "frames.json"
    kept = json.loads(old.read_text(encoding="utf-8")) if old.exists() else {}
    sets = dict(kept.get("sets", {}))          # sets this raw folder doesn't have stay as they were
    for name in ("peek", "cornerR", "cornerL", "top", "topL", "topR", "body"):
        entries = [f for f in meta["frames"] if f["set"] == name and (args.raw / f"{f['name']}.png").exists()]
        if entries:
            sets[name] = finish_set(name, entries, args.raw, args.out, args.ppm)
            print(f"{name}: {len(entries)} frames, {sets[name]['size'][0]}x{sets[name]['size'][1]}")
    (args.out / "frames.json").write_text(json.dumps({
        "model": meta["model"].get("title"),
        "name": args.name or kept.get("name") or args.out.name.title(),
        "voice": args.voice or kept.get("voice"),
        "pxPerMetre": args.ppm,
        "sets": sets,
    }, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
