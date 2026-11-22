# ruff: noqa: INP001, T201
"""Render the component tables of windows/THIRD_PARTY.md from windows/build/manifest.json.

    python windows/build/make-third-party.py          # rewrite the tables
    python windows/build/make-third-party.py --check  # exit 1 if THIRD_PARTY.md is out of date

Only the text between the BEGIN/END markers is replaced; everything else in the file is
written by hand.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "windows" / "build" / "manifest.json"
TARGET = ROOT / "windows" / "THIRD_PARTY.md"

SECTIONS = {
    "bundled": ("BUNDLED", "License"),
    "dev": ("DEV", "License"),
}
HEADER = ("Component", "Version", "License", "Source", "Notes")


def cell(value: str) -> str:
    return value.replace("|", "\\|").strip()


def table(rows: list[dict]) -> str:
    lines = [
        "| " + " | ".join(HEADER) + " |",
        "| " + " | ".join("---" for _ in HEADER) + " |",
    ]
    for r in rows:
        notes = r.get("notes", "")
        if r.get("sha256"):
            notes = (notes + " " if notes else "") + f"SHA256 `{r['sha256']}`."
        lines.append(
            "| "
            + " | ".join(
                cell(x)
                for x in (r["name"], r["version"], r["license"], r["source"], notes)
            )
            + " |",
        )
    return "\n".join(lines)


def render(text: str, inputs: list[dict]) -> str:
    for scope, (marker, _) in SECTIONS.items():
        begin, end = f"<!-- BEGIN {marker} -->", f"<!-- END {marker} -->"
        if begin not in text or end not in text:
            msg = f"{TARGET} lacks the {begin} / {end} markers"
            raise SystemExit(msg)
        rows = [r for r in inputs if r["scope"] == scope]
        head, rest = text.split(begin, 1)
        _, tail = rest.split(end, 1)
        text = f"{head}{begin}\n{table(rows)}\n{end}{tail}"
    return text


def main() -> int:
    inputs = json.loads(MANIFEST.read_text(encoding="utf-8"))["inputs"]
    current = TARGET.read_text(encoding="utf-8").replace("\r\n", "\n")
    updated = render(current, inputs)
    if "--check" in sys.argv:
        if updated != current:
            print(
                "windows/THIRD_PARTY.md is out of date: run python windows/build/make-third-party.py",
            )
            return 1
        print("OK: windows/THIRD_PARTY.md matches windows/build/manifest.json")
        return 0
    if updated != current:
        TARGET.write_text(updated, encoding="utf-8", newline="\n")
        print("updated windows/THIRD_PARTY.md")
    else:
        print("windows/THIRD_PARTY.md already up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
