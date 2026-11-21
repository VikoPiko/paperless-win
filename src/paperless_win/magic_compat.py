r"""Unicode-safe, more accurate ``magic.from_file`` for Windows.

The libmagic DLL we ship (D8) is a 2018 build with two problems:

* It opens files through the ANSI C runtime, so a path with characters outside the current
  code page (``Müller Rechnung.pdf``, a profile such as ``C:\Users\Jürgen``) fails with
  "cannot open ... (No such file or directory)". Upstream calls
  ``magic.from_file(path, mime=True)`` for every consumed file.
* It does not know HEIC/HEIF/AVIF images (iPhone photos, reported as
  ``application/octet-stream``) or Office Open XML packages (octet-stream/zip).

``install()`` (called from ``bootstrap.apply()``, Windows only) swaps in a wrapper that
reads the head of the file in Python and passes the bytes to ``magic.from_buffer`` when
the path is not pure ASCII (ASCII paths still go through libmagic itself; libmagic only
looks at the first 1 MiB anyway), then corrects the two gaps above.
"""

from __future__ import annotations

import os
import zipfile
from typing import Any

HEAD_BYTES = 1024 * 1024
UNKNOWN = ("application/octet-stream", "application/zip")

# ISO base media "ftyp" brands. The libmagic we ship (2018) does not know any of them.
_HEIC_BRANDS = {b"heic", b"heix", b"heim", b"heis", b"hevc", b"hevx", b"hevm", b"hevs"}
_HEIF_BRANDS = {b"mif1", b"msf1"}
_AVIF_BRANDS = {b"avif", b"avis"}

_OOXML = {
    "word/": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xl/": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "ppt/": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


def sniff_heif(head: bytes) -> str | None:
    """``image/heic`` etc. from the ``ftyp`` box at the start of a HEIF container."""
    if len(head) < 12 or head[4:8] != b"ftyp":
        return None
    brand = head[8:12]
    if brand in _HEIC_BRANDS:
        return "image/heic"
    if brand in _HEIF_BRANDS:
        return "image/heif"
    if brand in _AVIF_BRANDS:
        return "image/avif"
    return None


def sniff_ooxml(path: str) -> str | None:
    """Word/Excel/PowerPoint mime type from the entries of an OOXML zip package."""
    try:
        if not zipfile.is_zipfile(path):
            return None
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
    except (OSError, zipfile.BadZipFile):
        return None
    if "[Content_Types].xml" not in names:
        return None
    for prefix, mime in _OOXML.items():
        if any(name.startswith(prefix) for name in names):
            return mime
    return None


def refine(mime: str, head: bytes, path: str) -> str:
    """Correct the types the old libmagic reports as generic binary or zip."""
    if mime not in UNKNOWN:
        return mime
    return sniff_heif(head) or sniff_ooxml(path) or mime


def make_from_file(original: Any, from_buffer: Any) -> Any:
    def from_file(filename: Any, mime: bool = False) -> str:  # noqa: FBT001, FBT002
        path = os.fspath(filename)
        text = path.decode("utf-8", "replace") if isinstance(path, bytes) else path
        with open(path, "rb") as handle:  # noqa: PTH123 - mirrors libmagic's plain open
            head = handle.read(HEAD_BYTES)
        # ASCII paths keep the original code path; others cannot be opened by libmagic
        result = (
            original(path, mime=mime)
            if text.isascii()
            else from_buffer(head, mime=mime)
        )
        return refine(result, head, text) if mime else result

    from_file._winport = True  # type: ignore[attr-defined]
    return from_file


def install() -> bool:
    """Patch ``magic.from_file`` once. Returns True if the patch is (now) in place."""
    import magic

    if getattr(magic.from_file, "_winport", False):
        return True
    magic.from_file = make_from_file(magic.from_file, magic.from_buffer)
    return True
