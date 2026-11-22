from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest

from paperless_win import files
from paperless_win import platform

if TYPE_CHECKING:
    from pathlib import Path


def test_open_and_discard_removes_file_once_closed(tmp_path: Path) -> None:
    target = tmp_path / "download.zip"
    target.write_bytes(b"payload")
    handle = files.open_and_discard(target)
    try:
        assert handle.read() == b"payload"
    finally:
        handle.close()
    assert not target.exists()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX unlink-while-open semantics")
def test_linux_branch_unlinks_immediately(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(platform, "IS_WINDOWS", False)
    target = tmp_path / "x.bin"
    target.write_bytes(b"data")
    handle = files.open_and_discard(target)
    try:
        assert not target.exists()  # POSIX: unlinked while open
        assert handle.read() == b"data"
    finally:
        handle.close()
