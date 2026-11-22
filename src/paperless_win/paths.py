"""Path storage and Windows-safe file names.

Rules (see ``windows/tasks/03-paths-filenames.md``):

* Paths stored in the database and in export manifests are always POSIX
  (``a/b/c.pdf``), relative, on every OS. ``to_db`` / ``from_db`` are the two
  conversion points.
* Generated storage paths must be legal on NTFS. On Windows each path component is
  sanitised (reserved device names, illegal characters, trailing dots and spaces) and
  the whole path is kept under ``MAX_PATH`` by shortening the file name. We chose
  truncation over ``\\\\?\\`` long paths because it works without the
  ``LongPathsEnabled`` registry switch and with every tool we shell out to.
  Set ``PAPERLESS_WIN_MAX_PATH`` (default 259) higher if long paths are enabled.
* On Linux every function that changes a name is a no-op.

Windows behaviour is selected through ``paperless_win.platform.IS_WINDOWS`` at call time,
so tests can monkeypatch it and exercise the Windows branch on Linux.
"""

from __future__ import annotations

import os
from pathlib import Path
from pathlib import PurePath
from pathlib import PurePosixPath
from pathlib import PureWindowsPath

import pathvalidate

from paperless_win import platform

DEFAULT_MAX_PATH = 259  # MAX_PATH (260) minus the terminating NUL
# Room kept free after the template for "_v12", "_01" and an extension such as ".jpeg"
DEFAULT_RESERVE = 24
_MIN_STEM = 8  # never shorten a file name below this many characters


def to_db(path: PurePath | str) -> str:
    """Relative POSIX string for storing in the database or a manifest.

    Accepts either separator when given a string on Windows. Absolute paths and paths
    with a drive are rejected: only relative paths are stored.
    """
    if isinstance(path, str):
        pure: PurePath = (
            PureWindowsPath(path) if platform.IS_WINDOWS else PurePosixPath(path)
        )
    else:
        pure = path
    if pure.anchor:  # a drive and/or a leading separator
        msg = f"Only relative paths can be stored, got {path!r}"
        raise ValueError(msg)
    return pure.as_posix()


def from_db(stored: str) -> Path:
    """``Path`` for a stored relative string. Tolerates ``\\`` in rows written by old
    Windows installs; on Linux a backslash is a legal file name character, so rows are
    left alone."""
    if platform.IS_WINDOWS:
        stored = stored.replace("\\", "/")
    return Path(stored)


def sanitize_component(name: str) -> str:
    """Make one path component legal on NTFS (Windows only; identity on Linux)."""
    if not platform.IS_WINDOWS or name in {"", ".", ".."}:
        return name
    cleaned = pathvalidate.sanitize_filename(
        name,
        replacement_text="_",
        platform="windows",
    )
    # pathvalidate returns "" for names that are nothing but invalid characters, and
    # leaves a trailing "." on some inputs once reserved names are handled
    cleaned = cleaned.rstrip(". ")
    return cleaned or "_"


def sanitize_relative_path(rel: str) -> str:
    """Sanitise every ``/``-separated component of a template result."""
    if not platform.IS_WINDOWS:
        return rel
    return "/".join(sanitize_component(part) for part in rel.split("/"))


def max_path() -> int:
    raw = os.environ.get("PAPERLESS_WIN_MAX_PATH")
    if raw and raw.isdigit() and int(raw) > 0:
        return int(raw)
    return DEFAULT_MAX_PATH


def fits_max_path(root: Path, rel: str, *, reserve: int = 0) -> bool:
    """Would ``root/rel`` plus ``reserve`` extra characters stay within the limit?"""
    return len(str(root / rel)) + reserve <= max_path()


def shorten_to_fit(
    root: Path,
    rel: str,
    *,
    reserve: int = DEFAULT_RESERVE,
) -> str | None:
    """Shorten the final component of ``rel`` until ``root/rel`` fits.

    Directory components are never touched. Returns ``None`` when even a minimal
    file name does not fit; callers then fall back to ID-based naming.
    """
    if fits_max_path(root, rel, reserve=reserve):
        return rel
    head, _, tail = rel.rpartition("/")
    prefix = f"{head}/" if head else ""
    # Characters over the limit once the reserve is counted; only the file name shrinks
    excess = len(str(root / rel)) + reserve - max_path()
    keep = len(tail) - excess
    if keep < _MIN_STEM:
        return None
    return f"{prefix}{tail[:keep].rstrip('. ')}" or None


def finalize_relative_path(
    rel: str,
    root: Path,
    *,
    reserve: int = DEFAULT_RESERVE,
) -> str | None:
    """Single entry point used by ``documents.file_handling.format_filename``.

    Linux: returns ``rel`` unchanged. Windows: sanitises each component, then shortens
    the file name so the path fits. ``None`` means "cannot be made to fit".
    """
    if not platform.IS_WINDOWS:
        return rel
    return shorten_to_fit(root, sanitize_relative_path(rel), reserve=reserve)


# Keys the exporter writes (documents.settings.EXPORTER_*_NAME) and the model fields that hold
# stored relative paths. Duplicated as literals so this module never imports Django models.
_MANIFEST_PATH_KEYS = (
    "__exported_file_name__",
    "__exported_thumbnail_name__",
    "__exported_archive_name__",
    "__exported_share_link_bundle_name__",
)
_MANIFEST_PATH_FIELDS = ("filename", "archive_filename", "file_path")


def normalize_manifest_record(record: dict) -> dict:
    """Accept ``\\`` as well as ``/`` in the paths of an export manifest record.

    Called for every record the importer reads. The exporter always writes ``/``, so this
    only matters for hand-edited or foreign manifests. Windows only: there ``\\`` can never
    be part of a file name, so converting it is always correct; on Linux it would be.
    """
    if not platform.IS_WINDOWS:
        return record
    for key in _MANIFEST_PATH_KEYS:
        value = record.get(key)
        if isinstance(value, str):
            record[key] = value.replace("\\", "/")
    fields = record.get("fields")
    if isinstance(fields, dict):
        for name in _MANIFEST_PATH_FIELDS:
            value = fields.get(name)
            if isinstance(value, str):
                fields[name] = value.replace("\\", "/")
    return record
