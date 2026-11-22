from __future__ import annotations

import zipfile
from typing import TYPE_CHECKING

import magic
import pikepdf
import pytest
from PIL import Image

from paperless_win import magic_compat as compat

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(scope="module", autouse=True)
def patched_magic():
    """Install the wrapper for these tests only, restore afterwards."""
    original = magic.from_file
    compat.install()
    yield
    magic.from_file = original


def ooxml(path: Path, folder: str) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("_rels/.rels", "<Relationships/>")
        z.writestr(f"{folder}document.xml", "<x/>")
    return path


def heif_header(brand: bytes) -> bytes:
    return b"\x00\x00\x00\x18ftyp" + brand + b"\x00\x00\x00\x00" + brand + b"mif1"


class TestSniffing:
    @pytest.mark.parametrize(
        ("brand", "expected"),
        [
            (b"heic", "image/heic"),
            (b"heix", "image/heic"),
            (b"mif1", "image/heif"),
            (b"avif", "image/avif"),
            (b"mp42", None),  # an MP4 video must stay untouched
            (b"qt  ", None),
        ],
    )
    def test_heif_brands(self, brand: bytes, expected: str | None) -> None:
        assert compat.sniff_heif(heif_header(brand)) == expected

    def test_short_or_non_heif_data(self) -> None:
        assert compat.sniff_heif(b"") is None
        assert compat.sniff_heif(b"%PDF-1.7") is None

    @pytest.mark.parametrize(
        ("folder", "expected"),
        [
            (
                "word/",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
            (
                "xl/",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
            (
                "ppt/",
                "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            ),
        ],
    )
    def test_ooxml_packages(self, tmp_path: Path, folder: str, expected: str) -> None:
        assert compat.sniff_ooxml(str(ooxml(tmp_path / "x.zip", folder))) == expected

    def test_plain_zip_is_not_ooxml(self, tmp_path: Path) -> None:
        plain = tmp_path / "a.zip"
        with zipfile.ZipFile(plain, "w") as z:
            z.writestr("a.txt", "x")
        assert compat.sniff_ooxml(str(plain)) is None
        assert compat.sniff_ooxml(str(tmp_path / "missing.zip")) is None

    def test_refine_only_touches_generic_types(self, tmp_path: Path) -> None:
        heic = heif_header(b"heic")
        assert compat.refine("application/octet-stream", heic, "x") == "image/heic"
        assert compat.refine("image/png", heic, "x") == "image/png"


# Types the upstream parsers rely on. (docx/xlsx are only used with Tika, which is optional.)
SAMPLES = [
    "pdf",
    "png",
    "tiff",
    "jpeg",
    "gif",
    "webp",
    "heic",
    "eml",
    "txt",
    "docx",
    "xlsx",
]


def make_sample(kind: str, folder: Path) -> tuple[Path, str]:
    path = folder / f"sample.{kind}"
    if kind == "pdf":
        doc = pikepdf.new()
        doc.add_blank_page()
        doc.save(path)
        return path, "application/pdf"
    if kind in {"png", "tiff", "jpeg", "gif", "webp"}:
        Image.new("RGB", (32, 32), (10, 120, 200)).save(path, kind.upper())
        return path, f"image/{kind}"
    if kind == "heic":
        path.write_bytes(heif_header(b"heic") + b"\x00" * 64)
        return path, "image/heic"
    if kind == "eml":
        path.write_bytes(
            b"From: a@example.com\r\nTo: b@example.com\r\nSubject: hi\r\n"
            b"Message-ID: <1@example.com>\r\nMIME-Version: 1.0\r\n"
            b"Content-Type: text/plain\r\n\r\nhello\r\n",
        )
        return path, "message/rfc822"
    if kind == "txt":
        path.write_text("plain text\n", encoding="utf-8")
        return path, "text/plain"
    folder_name = "word/" if kind == "docx" else "xl/"
    sheet = "spreadsheetml.sheet" if kind == "xlsx" else "wordprocessingml.document"
    return (
        ooxml(path, folder_name),
        f"application/vnd.openxmlformats-officedocument.{sheet}",
    )


@pytest.mark.parametrize("folder_name", ["plain", "Tëst Dir with spaces ü", "日本語"])
@pytest.mark.parametrize("kind", SAMPLES)
def test_mime_detection_through_the_real_libmagic(
    tmp_path: Path,
    kind: str,
    folder_name: str,
) -> None:
    """Every type, in ASCII, accented, spaced and non-Latin directories."""
    folder = tmp_path / folder_name
    folder.mkdir()
    path, expected = make_sample(kind, folder)
    assert magic.from_file(path, mime=True) == expected


def test_non_mime_call_still_works(tmp_path: Path) -> None:
    path, _ = make_sample("txt", tmp_path)
    assert "text" in magic.from_file(path).lower()
