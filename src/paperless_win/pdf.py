"""PDF helpers that replace the ``qpdf`` and ``pdfinfo`` command-line tools on Windows.

pikepdf (already a dependency through OCRmyPDF) wraps the same qpdf library, so repairs
behave identically and we do not have to bundle two more executables. Linux keeps calling
the real tools: ``shim_subprocess`` declines everything on non-Windows.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import pikepdf

from paperless_win import platform

logger = logging.getLogger("paperless.winport.pdf")


def repair_in_place(path: Path) -> None:
    """Rewrite ``path`` through qpdf's library, repairing a damaged xref table.

    Equivalent to ``qpdf --replace-input <path>``. Raises
    ``subprocess.CalledProcessError`` when the file cannot be read at all, like the CLI.
    """
    try:
        # the CLI's exit code 3 ("repaired, with warnings") is a silent success here
        with pikepdf.open(path, allow_overwriting_input=True) as pdf:
            pdf.save(path)
    except (pikepdf.PdfError, pikepdf.PasswordError, OSError) as exc:
        raise subprocess.CalledProcessError(
            2,
            ["qpdf", str(path)],
            stderr=str(exc),
        ) from exc


_QPDF_FLAGS = frozenset({"--replace-input", "--warning-exit-0"})


def shim_subprocess(
    arguments: list[str],
    logger: logging.Logger | None = None,
) -> subprocess.CompletedProcess | None:
    """Handle ``qpdf --replace-input`` in-process on Windows.

    Called first thing in ``documents.utils.run_subprocess``. Returns a
    ``CompletedProcess`` when the call was handled, or ``None`` to let the real
    subprocess run (always the case on Linux, and for any other tool or option).
    """
    if not platform.IS_WINDOWS or not arguments:
        return None
    name = str(arguments[0]).lower().removesuffix(".exe")
    if name != "qpdf" or len(arguments) < 3:
        return None
    flags, target = [str(a) for a in arguments[1:-1]], arguments[-1]
    if "--replace-input" not in flags or not set(flags) <= _QPDF_FLAGS:
        return None
    repair_in_place(Path(target))
    if logger:
        logger.info("qpdf replaced by pikepdf: repaired %s", target)
    return subprocess.CompletedProcess(arguments, 0, b"", b"")


def _inherited(obj: pikepdf.Object, key: str) -> pikepdf.Object | None:
    """Look ``key`` up on a page and, if missing, on its ``/Parent`` chain."""
    seen = 0
    while obj is not None and seen < 64:  # bounded: a broken file may loop
        if key in obj:
            return obj[key]
        obj = obj.get("/Parent")
        seen += 1
    return None


def _box(obj: pikepdf.Object, key: str) -> tuple[float, float, float, float] | None:
    raw = _inherited(obj, key)
    if raw is None:
        return None
    try:
        x1, y1, x2, y2 = (float(v) for v in raw)
    except (TypeError, ValueError):
        return None
    return min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)


def first_page_size_points(
    path: Path,
    log: logging.Logger | None = None,
) -> tuple[float, float] | None:
    """``(width, height)`` in points of page 1, after rotation, like ``pdfinfo``.

    Matches what ``pdftoppm -cropbox`` renders: the CropBox clipped to the MediaBox
    (CropBox defaults to the MediaBox), then width and height swapped for 90/270 degree
    rotation. ``None`` if the file cannot be read, has no pages or a degenerate size.
    """
    log = log or logger
    try:
        with pikepdf.open(path) as pdf:
            if not pdf.pages:
                return None
            page = pdf.pages[0].obj
            media = _box(page, "/MediaBox") or (0.0, 0.0, 612.0, 792.0)
            crop = _box(page, "/CropBox") or media
            rotate = _inherited(page, "/Rotate")
            rotation = int(rotate) % 360 if rotate is not None else 0
    except (
        pikepdf.PdfError,
        pikepdf.PasswordError,
        OSError,
        ValueError,
        TypeError,
    ) as exc:
        log.warning("Could not determine PDF page size for %s: %s", path, exc)
        return None

    left, bottom = max(media[0], crop[0]), max(media[1], crop[1])
    right, top = min(media[2], crop[2]), min(media[3], crop[3])
    width, height = right - left, top - bottom
    if width <= 0 or height <= 0:
        return None
    if rotation in (90, 270):
        width, height = height, width
    return width, height


def page_size_hook(
    path: Path,
    log: logging.Logger | None = None,
) -> tuple[float, float] | None:
    """Windows replacement for the ``pdfinfo`` call in ``get_pdf_first_page_size_points``.

    Returns ``NotImplemented`` on other platforms so the upstream code carries on.
    """
    if not platform.IS_WINDOWS:
        return NotImplemented
    return first_page_size_points(path, log)
