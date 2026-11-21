"""pytest plugin: skip upstream tests that cannot pass on Windows, from a reviewed list.

Enabled with ``-p paperless_win.pytest_plugin`` (put ``PYTHONPATH=src`` and
``PYTEST_ADDOPTS="-p paperless_win.pytest_plugin"`` in the environment; the Windows CI
job and ``windows/scripts/run-tests.ps1`` do). It does nothing on other platforms, so
Linux runs are untouched and no upstream test file has to be edited.

The list lives in ``windows/skipped_tests.toml``. Every entry needs a ``reason`` and a
``follow_up``; ``windows/SKIPPED_TESTS.md`` explains the policy (CLAUDE.md rule 5).
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterable

SKIP_FILE = Path(__file__).resolve().parents[2] / "windows" / "skipped_tests.toml"


def load_entries(path: Path = SKIP_FILE) -> list[dict]:
    if not path.is_file():
        return []
    entries = tomllib.loads(path.read_text(encoding="utf-8")).get("skip", [])
    for entry in entries:
        missing = {"reason", "follow_up", "tests"} - entry.keys()
        if missing:
            msg = f"{path}: skip entry {entry!r} is missing {sorted(missing)}"
            raise ValueError(msg)
    return entries


def matches(nodeid: str, patterns: Iterable[str]) -> bool:
    """Exact node id, or a prefix ending at a ``::`` or ``[`` boundary (module, class,
    function or all parametrisations of it)."""
    nodeid = nodeid.replace("\\", "/")
    for pattern in patterns:
        if nodeid == pattern or nodeid.startswith((f"{pattern}::", f"{pattern}[")):
            return True
    return False


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    if sys.platform != "win32":
        return
    entries = load_entries()
    for item in items:
        for entry in entries:
            if matches(item.nodeid, entry["tests"]):
                item.add_marker(
                    pytest.mark.skip(
                        reason=f"winport: {entry['reason']} (follow-up: {entry['follow_up']})",
                    ),
                )
                break
