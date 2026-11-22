# ruff: noqa: INP001, T201
"""Make the Office fixtures in windows/fixtures/office/ (DOCX, ODT, XLSX, PPTX and an HTML e-mail).

    python windows/scripts/make_office_fixtures.py [--soffice PATH]

Each file contains the word ``kingfisher`` (the integration test looks for it in the OCR/Tika text).
The documents are written as flat ODF XML and converted with LibreOffice, so no other library is
needed. The result is committed; run this only to change the fixtures.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from email.message import EmailMessage
from pathlib import Path

WORD = "kingfisher"
ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "windows" / "fixtures" / "office"

NAMESPACES = (
    'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
    'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
    'xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0" '
    'xmlns:presentation="urn:oasis:names:tc:opendocument:xmlns:presentation:1.0" '
    'xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0" '
)


def flat(kind: str, body: str) -> str:
    mime = f"application/vnd.oasis.opendocument.{kind}"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<office:document {NAMESPACES} office:version="1.3" office:mimetype="{mime}">'
        f"<office:body>{body}</office:body></office:document>"
    )


TEXT = flat(
    "text",
    f"<office:text><text:h>Office fixture</text:h><text:p>The {WORD} sits on a branch above the river.</text:p>"
    "<text:p>Second paragraph with a number 20261122.</text:p></office:text>",
)
SHEET = flat(
    "spreadsheet",
    '<office:spreadsheet><table:table table:name="Birds"><table:table-row>'
    '<table:table-cell office:value-type="string"><text:p>species</text:p></table:table-cell>'
    '<table:table-cell office:value-type="string"><text:p>count</text:p></table:table-cell></table:table-row>'
    '<table:table-row><table:table-cell office:value-type="string">'
    f"<text:p>{WORD}</text:p></table:table-cell>"
    '<table:table-cell office:value-type="float" office:value="7"><text:p>7</text:p></table:table-cell>'
    "</table:table-row></table:table></office:spreadsheet>",
)
SLIDES = flat(
    "presentation",
    '<office:presentation><draw:page draw:name="page1"><draw:frame svg:width="20cm" svg:height="3cm" '
    'svg:x="2cm" svg:y="2cm" presentation:class="title"><draw:text-box>'
    f"<text:p>The {WORD} presentation</text:p></draw:text-box></draw:frame></draw:page></office:presentation>",
)


def convert(
    soffice: str,
    source: Path,
    target_format: str,
    out_dir: Path,
    profile: Path,
) -> Path:
    command = [
        soffice,
        "--headless",
        "--norestore",
        "--nolockcheck",
        "--nodefault",
        f"-env:UserInstallation={profile.as_uri()}",
        "--convert-to",
        target_format,
        "--outdir",
        str(out_dir),
        str(source),
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    produced = out_dir / f"{source.stem}.{target_format}"
    if not produced.is_file():
        msg = (
            f"LibreOffice did not make {produced.name}: {result.stdout} {result.stderr}"
        )
        raise SystemExit(msg)
    return produced


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--soffice",
        default=shutil.which("soffice")
        or str(ROOT / ".tools/libreoffice/program/soffice.exe"),
    )
    args = parser.parse_args()
    TARGET.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp_name:
        tmp = Path(tmp_name)
        profile = tmp / "profile"
        text = tmp / "fixture-text.fodt"
        sheet = tmp / "fixture-sheet.fods"
        slides = tmp / "fixture-slides.fodp"
        text.write_text(TEXT, encoding="utf-8")
        sheet.write_text(SHEET, encoding="utf-8")
        slides.write_text(SLIDES, encoding="utf-8")
        for source, fmt in (
            (text, "docx"),
            (text, "odt"),
            (sheet, "xlsx"),
            (slides, "pptx"),
        ):
            produced = convert(args.soffice, source, fmt, tmp, profile)
            shutil.copy(
                produced,
                TARGET / f"office-{source.stem.removeprefix('fixture-')}.{fmt}",
            )
    mail = EmailMessage()
    mail["From"] = "Birdwatcher <birds@example.com>"
    mail["To"] = "Archive <archive@example.com>"
    mail["Subject"] = f"A {WORD} report"
    mail["Date"] = "Sat, 22 Nov 2026 10:00:00 +0000"
    mail.set_content(f"The {WORD} was seen at the lake.")
    mail.add_alternative(
        f"<html><body><h1>Report</h1><p>The <b>{WORD}</b> was seen at the lake.</p></body></html>",
        subtype="html",
    )
    (TARGET / "office-mail.eml").write_bytes(mail.as_bytes())
    for produced in sorted(TARGET.iterdir()):
        print(f"{produced.name}: {produced.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
