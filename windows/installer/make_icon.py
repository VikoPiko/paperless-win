# ruff: noqa: INP001, T201
"""Draw windows/installer/paperless-win.ico (an original icon; it is not the paperless-ngx logo).

    python windows/installer/make_icon.py

Two sheets of paper with a coloured band on a rounded dark-blue square. Needs Pillow (a
dependency of the project). The .ico is committed; run this only to change the design.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image
from PIL import ImageDraw

TARGET = Path(__file__).with_name("paperless-win.ico")
SIZE = 1024  # drawn large, then scaled down for a smooth edge
BLUE = (24, 54, 92, 255)
PAPER = (250, 250, 247, 255)
SHADE = (190, 201, 214, 255)
ACCENT = (242, 153, 40, 255)
INK = (96, 112, 134, 255)


def draw() -> Image.Image:
    image = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(image)
    d.rounded_rectangle((40, 40, SIZE - 40, SIZE - 40), radius=190, fill=BLUE)
    # the sheet behind, turned a little to the right
    d.polygon([(330, 170), (700, 170), (850, 320), (850, 830), (330, 830)], fill=SHADE)
    # the sheet in front with a folded corner
    d.polygon([(230, 230), (600, 230), (750, 380), (750, 890), (230, 890)], fill=PAPER)
    d.polygon([(600, 230), (750, 380), (600, 380)], fill=SHADE)
    # text lines, the first one in the accent colour
    d.rounded_rectangle((300, 470, 690, 520), radius=25, fill=ACCENT)
    for y in (580, 670, 760):
        d.rounded_rectangle(
            (300, y, 690 if y != 760 else 520, y + 44),
            radius=22,
            fill=INK,
        )
    return image


def main() -> None:
    sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (24, 24), (16, 16)]
    draw().save(TARGET, format="ICO", sizes=sizes)
    print(f"wrote {TARGET} ({TARGET.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
