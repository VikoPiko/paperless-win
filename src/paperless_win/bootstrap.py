"""One-time process setup for Windows: tool folders on PATH, libmagic, sane defaults.

``apply()`` is called once from ``paperless/settings/__init__.py`` (after
``paperless.conf`` has been read, so values from that file win over our defaults).
It does nothing on Linux. Everything uses ``os.environ.setdefault`` semantics, so an
explicit user setting is never overridden.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from paperless_win import magic_compat
from paperless_win import platform

if TYPE_CHECKING:
    from pathlib import Path

# Keeps os.add_dll_directory() handles alive; closing them would remove the directory.
_dll_dir_handles: list[object] = []


def _prepend_path(directories: list[Path]) -> None:
    current = os.environ.get("PATH", "")
    existing = {p.lower() for p in current.split(os.pathsep) if p}
    new = [str(d) for d in directories if str(d).lower() not in existing]
    if new:
        os.environ["PATH"] = os.pathsep.join([*new, current] if current else new)


def _append_path(directories: list[Path]) -> None:
    current = os.environ.get("PATH", "")
    existing = {p.lower() for p in current.split(os.pathsep) if p}
    new = [str(d) for d in directories if str(d).lower() not in existing]
    if new:
        os.environ["PATH"] = os.pathsep.join([current, *new] if current else new)


def _find_in(directories: list[Path], filename: str) -> Path | None:
    for directory in directories:
        candidate = directory / filename
        if candidate.is_file():
            return candidate
    return None


def apply() -> None:
    """Idempotent. Safe to call more than once and on any OS."""
    if not platform.IS_WINDOWS:
        return

    dirs = platform.bin_dirs()
    _prepend_path(dirs)
    _append_path(
        platform.gpg_dirs(),
    )  # optional gpg: after our own tools, never in front

    add_dll_directory = getattr(os, "add_dll_directory", None)
    if add_dll_directory is not None:
        for directory in dirs:
            try:
                _dll_dir_handles.append(add_dll_directory(str(directory)))
            except OSError:
                continue  # vanished between the walk and now

    # python-magic finds libmagic-1.dll through PATH; the database needs MAGIC (D8)
    if "MAGIC" not in os.environ:
        mgc = _find_in(dirs, "magic.mgc")
        if mgc is not None:
            os.environ["MAGIC"] = str(mgc)

    # gpg needs a home directory; upstream falls back to /tmp, which does not exist here
    os.environ.setdefault("HOME", str(platform.default_tmp_dir()))

    font = platform.default_font()
    if font.is_file():
        os.environ.setdefault("PAPERLESS_THUMBNAIL_FONT_NAME", str(font))

    # unpaper is not available on Windows (D10): the upstream default would fail every
    # consume. If the user supplies a binary, keep upstream's default.
    if platform.find_binary("unpaper") is None:
        os.environ.setdefault("PAPERLESS_OCR_CLEAN", "none")

    # libmagic cannot open non-ASCII paths on Windows (D8 follow-up)
    try:
        magic_compat.install()
    except ImportError:
        pass  # python-magic is not installed (e.g. a minimal test environment)
