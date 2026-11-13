"""Crops the raw renders from render.mjs to one shared box, scales them and makes a contact sheet.

    python scripts\\avatar_render\\finish.py D:\\RED\\models\\companion\\raw D:\\RED\\models\\companion\\sprites

Every frame gets the same crop, so the character never jumps between frames. The output folder gets
one PNG per frame, frames.json (names, states, emotions, size) and contact-sheet.png to look at.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ALPHA_MIN = 8
PAD = 16


def union_box(images: list[Image.Image]) -> tuple[int, int, int, int]:
    boxes = [img.getchannel("A").point(lambda a: 255 if a > ALPHA_MIN else 0).getbbox() for img in images]
    boxes = [b for b in boxes if b]
    if not boxes:
        raise SystemExit("every frame is empty: the model did not render")
    left = min(b[0] for b in boxes) - PAD
    top = min(b[1] for b in boxes) - PAD
    right = max(b[2] for b in boxes) + PAD
    bottom = max(b[3] for b in boxes) + PAD
    w, h = images[0].size
    return max(left, 0), max(top, 0), min(right, w), min(bottom, h)


def contact_sheet(frames: list[tuple[str, Image.Image]], path: Path, columns: int = 7) -> None:
    cell_h = 300
    scale = cell_h / frames[0][1].height
    cell_w = int(frames[0][1].width * scale)
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
        thumb = img.resize((cell_w, cell_h), Image.LANCZOS)
        sheet.paste(thumb, (x, y), thumb)
        draw.text((x + 6, y + cell_h + 4), name, fill=(30, 30, 40), font=font)
    sheet.save(path)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("raw", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--height", type=int, default=640, help="height of each output frame in pixels")
    args = ap.parse_args()

    meta = json.loads((args.raw / "frames.json").read_text(encoding="utf-8"))
    entries = [f for f in meta["frames"] if (args.raw / f"{f['name']}.png").exists()]
    images = [Image.open(args.raw / f"{f['name']}.png").convert("RGBA") for f in entries]
    box = union_box(images)
    crop_w, crop_h = box[2] - box[0], box[3] - box[1]
    width = round(crop_w * args.height / crop_h)

    args.out.mkdir(parents=True, exist_ok=True)
    done = []
    for entry, img in zip(entries, images):
        frame = img.crop(box).resize((width, args.height), Image.LANCZOS)
        frame.save(args.out / f"{entry['name']}.png", optimize=True)
        done.append((entry["name"], frame))

    (args.out / "frames.json").write_text(json.dumps({
        "model": meta["model"].get("title"),
        "size": [width, args.height],
        "anchor": "bottom-center",
        "frames": entries,
    }, indent=2), encoding="utf-8")
    contact_sheet(done, args.out / "contact-sheet.png")
    print(f"{len(done)} frames, {width}x{args.height}, sheet: {args.out / 'contact-sheet.png'}")


if __name__ == "__main__":
    main()
