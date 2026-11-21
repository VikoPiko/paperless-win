#!/usr/bin/env python3
# ruff: noqa: T201
"""Summarise a pytest JUnit XML report: failures grouped by exception type and module.

Usage:
    python windows/scripts/summarize_failures.py .spike/junit-windows.xml [--markdown]

Run pytest with ``--junitxml=<file>`` to produce the input. The raw log is never needed:
commit this summary, not the log.
"""

from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from collections import defaultdict
from pathlib import Path

# "E   FileNotFoundError: [WinError 2] ..." or "<class 'x.Y'>" or "ModuleName.ErrorName: msg"
EXC_LINE = re.compile(
    r"^E\s+(?P<exc>[A-Za-z_][\w.]*(?:Error|Exception|Exit|Warning|Failed|Interrupt))\b",
)
ASSERT_LINE = re.compile(r"^E\s+assert\b")


def exception_type(case: ET.Element) -> str:
    """Best-effort exception class of a failed/errored test case."""
    node = case.find("failure")
    if node is None:
        node = case.find("error")
    if node is None:
        return "?"
    message = node.get("message") or ""
    # junit "message" starts with the exception ("AssertionError: ..." / "assert 1 == 2")
    match = re.match(
        r"^(?:\w+\.)*?([A-Z]\w*(?:Error|Exception|Exit|Failed|Interrupt))\b",
        message,
    )
    if match:
        return match.group(1)
    if message.startswith(("assert", "AssertionError")):
        return "AssertionError"
    for line in (node.text or "").splitlines():
        found = EXC_LINE.match(line)
        if found:
            return found.group("exc").rsplit(".", 1)[-1]
        if ASSERT_LINE.match(line):
            return "AssertionError"
    return (message.split(":", 1)[0] or "?")[:60]


def module_of(case: ET.Element) -> str:
    # classname looks like "documents.tests.test_api.TestFoo" (module path + class)
    classname = case.get("classname", "")
    parts = classname.split(".")
    # drop trailing CamelCase class names
    while parts and parts[-1][:1].isupper():
        parts.pop()
    return ".".join(parts) or classname or "?"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("junit", type=Path)
    ap.add_argument("--markdown", action="store_true", help="emit Markdown tables")
    ap.add_argument("--top", type=int, default=25, help="rows per table")
    args = ap.parse_args()

    if not args.junit.is_file():
        print(f"error: {args.junit} not found", file=sys.stderr)
        return 2
    root = ET.parse(args.junit).getroot()
    cases = list(root.iter("testcase"))

    outcome: Counter[str] = Counter()
    by_exc: Counter[str] = Counter()
    by_module: Counter[str] = Counter()
    by_module_exc: dict[str, Counter[str]] = defaultdict(Counter)
    for case in cases:
        if case.find("failure") is not None or case.find("error") is not None:
            kind = "error" if case.find("error") is not None else "failed"
            outcome[kind] += 1
            exc = exception_type(case)
            mod = module_of(case)
            by_exc[exc] += 1
            by_module[mod] += 1
            by_module_exc[mod][exc] += 1
        elif case.find("skipped") is not None:
            outcome["skipped"] += 1
        else:
            outcome["passed"] += 1

    def table(title: str, rows: list[tuple[str, int]]) -> None:
        print(f"\n{'### ' if args.markdown else ''}{title}")
        if args.markdown:
            print("| Count | Name |\n|---:|---|")
            for name, count in rows:
                print(f"| {count} | `{name}` |")
        else:
            for name, count in rows:
                print(f"{count:6d}  {name}")

    total = len(cases)
    print(
        f"{'## ' if args.markdown else ''}Summary of {args.junit.name}: {total} test cases",
    )
    print(", ".join(f"{k}={v}" for k, v in sorted(outcome.items())))
    table("Failures by exception type", by_exc.most_common(args.top))
    table("Failures by module", by_module.most_common(args.top))
    print(f"\n{'### ' if args.markdown else ''}Top exception per failing module")
    for mod, count in by_module.most_common(args.top):
        exc, n = by_module_exc[mod].most_common(1)[0]
        print(f"{'- ' if args.markdown else '  '}{count:5d}  {mod}  ({exc} x{n})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
