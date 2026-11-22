# ruff: noqa: INP001
"""Generate synthetic, non-private test fixtures (image-only "scanned" PDFs, PNG, barcode page).

Usage: python windows/scripts/make_fixtures.py [--out DIR] [--smoke-only]
Needs Pillow and zxing-cpp (both are paperless-ngx dependencies). Uses Arial if present.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image
from PIL import ImageDraw
from PIL import ImageFont

KNOWN_WORD = "zebrafish"
FONT_CANDIDATES = (
    r"C:\Windows\Fonts\arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)


def font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in FONT_CANDIDATES:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default(size)


def page(lines: list[str]) -> Image.Image:
    """A 150 dpi A4-ish grayscale page of black text on white: needs OCR to be read."""
    img = Image.new("L", (1240, 1754), 255)
    draw = ImageDraw.Draw(img)
    y = 150
    for line in lines:
        draw.text((120, y), line, fill=0, font=font(54))
        y += 110
    return img


def barcode_page(text: str = "PATCHT") -> Image.Image:
    import numpy as np
    import zxingcpp

    code = zxingcpp.write_barcode(
        zxingcpp.BarcodeFormat.Code128,
        text,
        width=600,
        height=200,
    )
    img = Image.new("L", (1240, 1754), 255)
    img.paste(Image.fromarray(np.array(code)).convert("L"), (320, 400))
    return img


def save_pdf(pages: list[Image.Image], path: Path) -> None:
    pages[0].save(path, "PDF", resolution=150.0, save_all=True, append_images=pages[1:])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("windows/fixtures"))
    ap.add_argument("--smoke-only", action="store_true")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    smoke = page(
        [
            "Paperless Windows Smoke Test",
            f"Keyword: {KNOWN_WORD}",
            "Invoice 2026-0042",
            "Synthetic document, no personal data.",
        ],
    )
    save_pdf([smoke], args.out / "smoke.pdf")
    if args.smoke_only:
        return

    page(["Second Sample Image", "Keyword: quokkamarmalade", "Generated PNG"]).save(
        args.out / "image.png",
    )
    (args.out / "note.txt").write_text(
        "Plain text note.\nKeyword: narwhalpancake\n",
        encoding="utf-8",
    )
    save_pdf(
        [
            page(["Barcode part one", "Keyword: lemurtangerine"]),
            barcode_page(),
            page(["Barcode part two", "Keyword: ocelotbiscuit"]),
        ],
        args.out / "barcode.pdf",
    )


if __name__ == "__main__":
    main()
