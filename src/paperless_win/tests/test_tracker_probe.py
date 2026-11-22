from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest

from documents.management.commands.document_consumer import TrackedFile
from paperless_win.tests.test_fs import hold_open

if TYPE_CHECKING:
    from pathlib import Path

windows_only = pytest.mark.skipif(
    sys.platform != "win32",
    reason="real Windows file locking",
)


def tracked(path: Path) -> TrackedFile:
    item = TrackedFile(path=path, last_event_time=0.0)
    assert item.update_stats()
    return item


def test_unchanged_closed_file_is_stable(tmp_path: Path) -> None:
    target = tmp_path / "scan.pdf"
    target.write_bytes(b"data")
    assert tracked(target).is_unchanged()


def test_changed_file_is_not_stable(tmp_path: Path) -> None:
    target = tmp_path / "scan.pdf"
    target.write_bytes(b"data")
    item = tracked(target)
    target.write_bytes(b"more data")
    assert not item.is_unchanged()


@windows_only
def test_file_still_held_by_the_writer_is_not_stable(tmp_path: Path) -> None:
    """Size and mtime stop changing while a scanner still has the file open."""
    target = tmp_path / "scan.pdf"
    target.write_bytes(b"data")
    item = tracked(target)
    holder = hold_open(target, 1.0)
    try:
        assert not item.is_unchanged()
    finally:
        holder.wait(timeout=10)
    assert item.is_unchanged()
