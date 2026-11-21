"""File helpers for behaviours that differ between POSIX and Windows."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING
from typing import BinaryIO

from paperless_win import platform

if TYPE_CHECKING:
    from pathlib import Path


def open_and_discard(path: Path) -> BinaryIO:
    """Open ``path`` for reading and arrange for it to disappear once closed.

    POSIX (and therefore upstream) opens the file and unlinks it immediately; the open
    handle keeps the data alive. Windows refuses to delete a file that is open, so there
    the file is opened with ``O_TEMPORARY`` instead: it is deleted when the last handle
    is closed, which Django's ``FileResponse`` does after streaming.
    """
    if platform.IS_WINDOWS:
        fd = os.open(path, os.O_RDONLY | os.O_BINARY | os.O_TEMPORARY)  # type: ignore[attr-defined]
        return os.fdopen(fd, "rb")
    handle = path.open("rb")
    path.unlink()
    return handle
