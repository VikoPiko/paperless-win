# ruff: noqa: INP001, T201
"""Requirements of an extra only: ``all`` minus ``base``, as ``uv export`` wrote them.

    python split_requirements.py base.txt all.txt out.txt [--extra-index-url URL]

An entry is a line that starts a requirement (``name==version ; marker \\``) together with the
indented ``--hash=`` and ``# via`` lines below it. Entries whose first line also appears in
``base`` are dropped. The standard library only, so it runs with the bundled Python.
"""

from __future__ import annotations

import sys
from pathlib import Path


def entries(text: str) -> list[tuple[str, list[str]]]:
    """``(first_line, all_lines)`` for every requirement in the file."""
    found: list[tuple[str, list[str]]] = []
    current: list[str] | None = None
    for line in text.splitlines():
        if not line.strip() or line.startswith(("#", "--")):
            current = None
            continue
        if line[0] in " \t":
            if current is not None:
                current.append(line)
            continue
        current = [line]
        found.append((line.rstrip(" \\"), current))
    return found


def split(base: str, everything: str, index_url: str | None = None) -> str:
    known = {first for first, _ in entries(base)}
    out: list[str] = []
    if index_url:
        out.append(f"--extra-index-url {index_url}")
    for first, lines in entries(everything):
        if first not in known:
            out.extend(lines)
    return "\n".join(out) + "\n"


def main() -> int:
    args = sys.argv[1:]
    index = None
    if "--extra-index-url" in args:
        i = args.index("--extra-index-url")
        index = args[i + 1]
        del args[i : i + 2]
    base, everything, target = (Path(a) for a in args[:3])
    target.write_text(
        split(
            base.read_text(encoding="utf-8"),
            everything.read_text(encoding="utf-8"),
            index,
        ),
        encoding="ascii",
    )
    count = sum(1 for _ in entries(target.read_text(encoding="ascii")))
    print(f"{count} packages beyond the base install")
    return 0


if __name__ == "__main__":
    sys.exit(main())
