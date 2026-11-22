# ruff: noqa: INP001, T201
"""Is there a newer upstream paperless-ngx release than the one this fork is based on?

    python windows/scripts/upstream_watch.py [--tags-file FILE]

Reads the *tag names* of the public upstream repository (``git ls-remote --tags``, anonymous and
read-only; nothing is ever written there), picks the highest stable ``vX.Y.Z`` and compares it
with ``src/paperless/version.py``. When running in GitHub Actions it writes ``newer`` and ``tag``
to ``$GITHUB_OUTPUT``. The workflow then opens an issue on the fork; this script never does.
The standard library only.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

UPSTREAM_URL = "https://github.com/paperless-ngx/paperless-ngx.git"
ROOT = Path(__file__).resolve().parents[2]
TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")  # stable releases only: no -beta, no -rc


def parse_tag(tag: str) -> tuple[int, int, int] | None:
    match = TAG.match(tag.strip())
    return (int(match[1]), int(match[2]), int(match[3])) if match else None


def newest(tags: list[str]) -> tuple[int, int, int] | None:
    versions = [v for v in (parse_tag(t) for t in tags) if v]
    return max(versions) if versions else None


def tag_names(ls_remote_output: str) -> list[str]:
    """Tag names from ``git ls-remote --tags --refs`` output (``<sha>\trefs/tags/<name>``)."""
    names = []
    for line in ls_remote_output.splitlines():
        _, _, ref = line.partition("\t")
        if ref.startswith("refs/tags/"):
            names.append(ref.removeprefix("refs/tags/"))
    return names


def fork_version(version_py: Path) -> tuple[int, int, int]:
    match = re.search(
        r"__version__[^=]*=\s*\((\d+),\s*(\d+),\s*(\d+)\)",
        version_py.read_text(encoding="utf-8"),
    )
    if not match:
        msg = f"no version found in {version_py}"
        raise SystemExit(msg)
    return int(match[1]), int(match[2]), int(match[3])


def fmt(version: tuple[int, int, int]) -> str:
    return "v" + ".".join(map(str, version))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--tags-file",
        help="read `git ls-remote` output from a file (for tests)",
    )
    args = parser.parse_args()
    if args.tags_file:
        listing = Path(args.tags_file).read_text(encoding="utf-8")
    else:
        listing = subprocess.run(
            ["git", "ls-remote", "--tags", "--refs", UPSTREAM_URL, "v*"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    latest = newest(tag_names(listing))
    ours = fork_version(ROOT / "src" / "paperless" / "version.py")
    if latest is None:
        print("no upstream release tags found")
        return 1
    is_newer = latest > ours
    print(
        f"fork is based on {fmt(ours)}; newest upstream release is {fmt(latest)}; newer: {is_newer}",
    )
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with Path(out).open("a", encoding="utf-8") as fh:
            fh.write(f"newer={'true' if is_newer else 'false'}\ntag={fmt(latest)}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
