# ruff: noqa: INP001, T201
"""Generate N small, unique, non-private files for the consume soak test.

Every file carries a random 12-letter token as its only text, so a consumed document can
be matched back to exactly one input. Mix: 50% text files, 25% scanned-style PDFs (need
OCR), 25% PNG images (need OCR).

Usage: python make_soak_files.py <out_dir> [--count 200] [--seed 1]
Writes <out_dir>/<name> and <out_dir>/manifest.json ({"files": [{"name", "token", "kind"}]}).
"""

from __future__ import annotations

import argparse
import json
import random
import string
from pathlib import Path

from PIL import Image
from PIL import ImageDraw
from PIL import ImageFont

FONT_PATHS = (
    r"C:\Windows\Fonts\arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)


def font(size: int):
    for candidate in FONT_PATHS:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default(size)


def page(token: str) -> Image.Image:
    img = Image.new("L", (1240, 600), 255)
    draw = ImageDraw.Draw(img)
    draw.text((80, 120), "Soak test document", fill=0, font=font(54))
    draw.text((80, 260), token, fill=0, font=font(72))
    return img


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--count", type=int, default=200)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()
    rng = random.Random(args.seed)
    args.out.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    files = []
    for i in range(args.count):
        while (token := "".join(rng.choices(string.ascii_lowercase, k=12))) in seen:
            pass
        seen.add(token)
        kind = ("txt", "txt", "pdf", "png")[i % 4]
        name = f"soak-{i:03d}-{token[:4]}.{kind}"
        path = args.out / name
        if kind == "txt":
            path.write_text(f"Soak test note\n{token}\n", encoding="utf-8")
        elif kind == "pdf":
            page(token).save(path, "PDF", resolution=150.0)
        else:
            page(token).save(path, "PNG")
        files.append({"name": name, "token": token, "kind": kind})
    (args.out / "manifest.json").write_text(
        json.dumps({"files": files}, indent=1),
        encoding="utf-8",
    )
    print(f"generated {len(files)} files in {args.out}")


if __name__ == "__main__":
    main()
