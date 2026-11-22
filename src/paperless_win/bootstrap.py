"""One-time process setup for Windows: tool folders on PATH, libmagic, sane defaults.

``apply()`` is called once from ``paperless/settings/__init__.py`` (after
``paperless.conf`` has been read, so values from that file win over our defaults).
It does nothing on Linux. Everything uses ``os.environ.setdefault`` semantics, so an
explicit user setting is never overridden.
"""

from __future__ import annotations

import json
import logging
import os
from typing import TYPE_CHECKING

from paperless_win import fs
from paperless_win import magic_compat
from paperless_win import platform

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger("paperless.winport")

# Files that must never be consumed (regexes, matched against the file name). Upstream already
# ignores desktop.ini and Thumbs.db; these are the Windows-specific rest.
WINDOWS_IGNORE_PATTERNS = (
    r"^~\$.*",  # Office lock files: ~$report.docx
    r".*\.tmp$",
    r".*\.part$",
    r".*\.crdownload$",
)
NETWORK_POLLING_INTERVAL = (
    "10"  # seconds; native change events do not work on SMB shares
)

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

    from paperless_win import office

    office.install_error_details()  # gotenberg_client errors say what the server answered (P8)

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

    _merge_ignore_patterns()
    _default_polling_for_network_share()


def _merge_ignore_patterns() -> None:
    """Add the Windows junk patterns to ``PAPERLESS_CONSUMER_IGNORE_PATTERNS``.

    The user's own patterns are kept (ours are appended); an unparsable value is left for
    upstream's settings code to report.
    """
    raw = os.environ.get("PAPERLESS_CONSUMER_IGNORE_PATTERNS")
    try:
        current = json.loads(raw) if raw else []
    except ValueError:
        return
    if not isinstance(current, list):
        return
    merged = [*current, *(p for p in WINDOWS_IGNORE_PATTERNS if p not in current)]
    os.environ["PAPERLESS_CONSUMER_IGNORE_PATTERNS"] = json.dumps(merged)


def _default_polling_for_network_share() -> None:
    """Poll instead of waiting for change events when the consume folder is a network share."""
    folder = os.environ.get("PAPERLESS_CONSUMPTION_DIR")
    if not folder or "PAPERLESS_CONSUMER_POLLING_INTERVAL" in os.environ:
        return
    if fs.is_network_path(folder):
        os.environ["PAPERLESS_CONSUMER_POLLING_INTERVAL"] = NETWORK_POLLING_INTERVAL
        logger.info(
            "PAPERLESS_CONSUMPTION_DIR %s is a network share: polling every %ss, because "
            "file system events are not reliable on SMB. Set "
            "PAPERLESS_CONSUMER_POLLING_INTERVAL to override.",
            folder,
            NETWORK_POLLING_INTERVAL,
        )
