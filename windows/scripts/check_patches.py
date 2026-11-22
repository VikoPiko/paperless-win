# ruff: noqa: INP001, T201
"""Check that windows/PATCHES.md matches the files carrying `winport:` markers.

Files outside the fork-owned locations that contain the marker must be listed in the
table in windows/PATCHES.md, and every listed file must still contain the marker.
Exit code 0 on match, 1 on mismatch, 2 on usage/environment errors.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

MARKER = "winport:"
REPO_ROOT = Path(__file__).resolve().parents[2]
PATCHES_MD = REPO_ROOT / "windows" / "PATCHES.md"

# Fork-owned locations, as repo-relative POSIX paths (prefix match; "/" suffix = dir).
FORK_OWNED_PREFIXES = (
    "src/paperless_win/",
    "windows/",
    "CLAUDE.md",
    ".github/workflows/winport-",
)


def is_fork_owned(path: str) -> bool:
    return path.startswith(FORK_OWNED_PREFIXES)


def tracked_files() -> list[str]:
    """Tracked plus untracked-not-ignored files, so it works before the first commit."""
    out = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    ).stdout
    return [p for p in out.decode("utf-8").split("\0") if p]


def files_with_marker() -> set[str]:
    found: set[str] = set()
    for rel in tracked_files():
        if is_fork_owned(rel):
            continue
        path = REPO_ROOT / rel
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # binary or unreadable: cannot carry a text marker
        if MARKER in text:
            found.add(rel)
    return found


def listed_files() -> set[str]:
    """First column of the markdown table rows in PATCHES.md (backticked paths)."""
    listed: set[str] = set()
    for line in PATCHES_MD.read_text(encoding="utf-8").splitlines():
        if not line.lstrip().startswith("|"):
            continue
        first = line.strip().strip("|").split("|")[0].strip()
        match = re.fullmatch(r"`([^`]+)`", first)
        if match:
            listed.add(match.group(1).replace("\\", "/"))
    return listed


def main() -> int:
    if not PATCHES_MD.is_file():
        print(f"error: {PATCHES_MD} not found", file=sys.stderr)
        return 2
    try:
        marked = files_with_marker()
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(f"error: could not list files via git: {exc}", file=sys.stderr)
        return 2
    listed = listed_files()

    unregistered = sorted(marked - listed)
    stale = sorted(listed - marked)

    if unregistered:
        print(f"Files with '{MARKER}' markers but missing from windows/PATCHES.md:")
        for f in unregistered:
            print(f"  + {f}")
    if stale:
        print(f"Files listed in windows/PATCHES.md but with no '{MARKER}' marker:")
        for f in stale:
            print(f"  - {f}")
    if unregistered or stale:
        return 1

    print(f"OK: {len(marked)} patched upstream file(s), PATCHES.md matches.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
