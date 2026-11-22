"""Platform helpers: answers every "where is X on this OS" question.

Fork-owned. Upstream code reaches this module only through the small hooks listed in
``windows/PATCHES.md``. On Linux every function degrades to upstream's behaviour
(``find_binary`` is ``shutil.which``, ``config_search_paths`` is empty), so importing
and calling this module is always safe.

``IS_WINDOWS`` is read at call time through the module global, so tests can monkeypatch
it (and ``os.environ``) to exercise the Windows branches on Linux.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

IS_WINDOWS: bool = sys.platform == "win32"

# Ghostscript is the one binary whose name differs from upstream's ("gs").
_WINDOWS_NAMES: dict[str, tuple[str, ...]] = {
    "gs": ("gswin64c.exe", "gswin64.exe", "gs.exe"),
}

# Directories under a bin root that never contain tools we want on PATH.
_SKIP_DIRS = frozenset(
    {
        "dl",  # downloaded installers/archives (dev bootstrap)
        "7zip",
        "node",
        "node_modules",
        "service",
        "winsw",  # the service wrapper is not a tool for PATH
        "innosetup",  # installer compiler (dev only)
        "tessdata",
        "doc",
        "docs",
        "examples",
        "lib",
        "resource",
        "iccprofiles",
        "__pycache__",
    },
)
_MAX_WALK_DEPTH = 5
_EXE_SUFFIXES = (".exe",)


def app_dir() -> Path:
    """Install dir (installed layout) or the repo root (dev checkout).

    Both have this file at ``<root>/src/paperless_win/platform.py``. Set
    ``PAPERLESS_WIN_APP_DIR`` to override.
    """
    override = os.environ.get("PAPERLESS_WIN_APP_DIR")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2]


def program_data_dir() -> Path | None:
    """``%ProgramData%\\paperless-win`` on Windows, ``None`` elsewhere."""
    if not IS_WINDOWS:
        return None
    override = os.environ.get("PAPERLESS_WIN_DATA_ROOT")
    if (
        override
    ):  # the service integration test uses its own root, never a real installation's
        return Path(override)
    base = os.environ.get("PROGRAMDATA") or r"C:\ProgramData"
    return Path(base) / "paperless-win"


def config_search_paths() -> list[Path]:
    """Extra ``paperless.conf`` locations to try, in order. Empty on Linux."""
    if not IS_WINDOWS:
        return []
    paths: list[Path] = []
    data = program_data_dir()
    if data is not None:
        paths.append(data / "paperless.conf")
    paths.append(app_dir() / "paperless.conf")
    return paths


def default_tmp_dir() -> Path:
    return Path(tempfile.gettempdir())


def default_font() -> Path:
    """Serif font used to render text-document thumbnails."""
    if not IS_WINDOWS:
        return Path("/usr/share/fonts/liberation/LiberationSerif-Regular.ttf")
    candidates = [
        app_dir() / "windows" / "assets" / "fonts" / "LiberationSerif-Regular.ttf",
        app_dir() / "assets" / "fonts" / "LiberationSerif-Regular.ttf",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    windir = os.environ.get("WINDIR") or r"C:\Windows"
    return Path(windir) / "Fonts" / "times.ttf"


def _bin_roots() -> list[Path]:
    roots: list[Path] = []
    configured = os.environ.get("PAPERLESS_BIN_DIR")
    if configured:
        roots.append(Path(configured))
    roots.append(app_dir() / "bin")
    roots.append(
        app_dir() / ".tools",
    )  # dev checkout, see windows/scripts/bootstrap-dev.ps1
    return roots


def _is_tool_dir(files: list[str]) -> bool:
    lowered = [f.lower() for f in files]
    return any(f.endswith(_EXE_SUFFIXES) for f in lowered) or any(
        f.startswith("libmagic") and f.endswith(".dll") for f in lowered
    )


def bin_dirs() -> list[Path]:
    """Directories below the bin roots that contain executables (or libmagic).

    Shallowest first, then alphabetical, so the result is deterministic. Windows only;
    returns ``[]`` elsewhere.
    """
    if not IS_WINDOWS:
        return []
    found: list[Path] = []
    seen: set[Path] = set()
    for root in _bin_roots():
        if not root.is_dir():
            continue
        root_depth = len(root.parts)
        for current, dirnames, files in os.walk(root):
            here = Path(current)
            depth = len(here.parts) - root_depth
            dirnames[:] = sorted(
                d
                for d in dirnames
                if d.lower() not in _SKIP_DIRS and depth < _MAX_WALK_DEPTH
            )
            if depth > 0 and _is_tool_dir(files) and here not in seen:
                seen.add(here)
                found.append(here)
    found.sort(key=lambda p: (len(p.parts), str(p).lower()))
    return found


def gpg_dirs() -> list[Path]:
    """Folders of a user-installed Gpg4win / GnuPG for Windows that exist on this machine.

    gpg is optional (mail decryption only) and is not bundled, so we only look in the
    installers' default locations. Git for Windows' own msys gpg is deliberately ignored:
    it expects POSIX paths and cannot use a Windows ``GNUPGHOME``.
    """
    if not IS_WINDOWS:
        return []
    roots = [
        os.environ.get("PROGRAMFILES(X86)"),
        os.environ.get("PROGRAMFILES"),
        os.environ.get("LOCALAPPDATA")
        and str(Path(os.environ["LOCALAPPDATA"]) / "Programs"),
    ]
    found: list[Path] = []
    for root in roots:
        if not root:
            continue
        for sub in ("GnuPG/bin", "Gpg4win/bin", "GnuPG/bin_64"):
            candidate = Path(root) / sub
            if (candidate / "gpg.exe").is_file() and candidate not in found:
                found.append(candidate)
    return found


def _candidate_names(name: str) -> tuple[str, ...]:
    """Names to try via ``shutil.which``: the bare name first (which adds PATHEXT)."""
    return (name, *_WINDOWS_NAMES.get(name, ()))


def _exe_variants(candidate: str) -> tuple[str, ...]:
    return (candidate,) if Path(candidate).suffix else (f"{candidate}.exe", candidate)


def find_binary(name: str) -> str | None:
    """Locate a binary. On Linux this is exactly ``shutil.which``.

    On Windows, in order: ``PAPERLESS_BIN_<NAME>`` (authoritative override), ``PATH``
    (``bootstrap.apply()`` has normally put the bin directories there already), then any
    bin directory not yet on ``PATH`` (``PAPERLESS_BIN_DIR``, ``<app>/bin``,
    ``<app>/.tools``). Windows names are mapped (``gs`` becomes ``gswin64c.exe``) and
    ``.exe`` is added.

    Going through ``shutil.which`` first keeps upstream's tests, which mock it, valid.
    """
    if not IS_WINDOWS:
        return shutil.which(name)

    env_key = "PAPERLESS_BIN_" + name.upper().replace("-", "_")
    override = os.environ.get(env_key)
    if override:
        if Path(override).is_file():
            return str(Path(override))
        return shutil.which(override)

    names = _candidate_names(name)
    for candidate in names:
        found = shutil.which(candidate)
        if found:
            return found

    on_path = {p.lower() for p in os.environ.get("PATH", "").split(os.pathsep) if p}
    for directory in [*bin_dirs(), *gpg_dirs()]:
        if str(directory).lower() in on_path:
            continue
        for candidate in names:
            for variant in _exe_variants(candidate):
                path = directory / variant
                if path.is_file():
                    return str(path)
    return None
