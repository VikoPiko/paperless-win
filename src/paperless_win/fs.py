"""File-system helpers for Windows quirks: locked files, scanners, network shares.

* ``retry_io`` retries an operation that fails because another process (an antivirus
  scanner, the Windows search indexer, a scanner application) briefly holds the file.
* ``file_is_released`` tells the consumer whether a file can be opened exclusively, which
  is the only reliable "the writer is finished" signal on Windows.
* ``is_network_path`` detects UNC paths and mapped network drives.

On Linux ``retry_io`` calls the function exactly once and the probes answer "yes, ready" /
"no, local", so upstream behaviour is unchanged.
"""

from __future__ import annotations

import logging
import os
import time
from typing import TYPE_CHECKING
from typing import TypeVar

from paperless_win import platform

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

logger = logging.getLogger("paperless.winport.fs")

T = TypeVar("T")

# ERROR_SHARING_VIOLATION and ERROR_LOCK_VIOLATION
SHARING_VIOLATIONS = frozenset({32, 33})
DEFAULT_ATTEMPTS = 6
DEFAULT_BACKOFF = 0.16  # 0.16 + 0.32 + 0.64 + 1.28 + 2.56 = about 5 s in total


def is_transient(exc: BaseException) -> bool:
    """A failure that is worth retrying: a sharing violation or a plain PermissionError."""
    if isinstance(exc, PermissionError):
        return True
    return (
        isinstance(exc, OSError)
        and getattr(exc, "winerror", None) in SHARING_VIOLATIONS
    )


def retry_io(
    fn: Callable[[], T],
    *,
    attempts: int = DEFAULT_ATTEMPTS,
    backoff: float = DEFAULT_BACKOFF,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Call ``fn()``; on Windows retry transient lock errors with exponential backoff.

    Raises the last error once ``attempts`` are used up. On other platforms ``fn`` runs
    once and its errors propagate untouched.
    """
    if not platform.IS_WINDOWS:
        return fn()
    delay = backoff
    for attempt in range(1, max(attempts, 1) + 1):
        try:
            return fn()
        except OSError as exc:
            if not is_transient(exc) or attempt >= attempts:
                raise
            logger.debug(
                "File busy (%s), retry %d/%d in %.2fs",
                exc,
                attempt,
                attempts,
                delay,
            )
            sleep(delay)
            delay *= 2
    raise AssertionError("unreachable")  # pragma: no cover


def file_is_released(path: Path) -> bool:
    """True if no other process has ``path`` open (Windows: open with no sharing allowed).

    Anything other than a sharing/lock violation (file gone, no permission) counts as
    "released": the caller's other checks deal with those. Always True off Windows.
    """
    if not platform.IS_WINDOWS:
        return True
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    generic_read, share_none, open_existing = 0x80000000, 0, 3
    handle = kernel32.CreateFileW(
        os.fspath(path),
        generic_read,
        share_none,
        None,
        open_existing,
        0,
        None,
    )
    invalid = wintypes.HANDLE(-1).value
    if handle == invalid or handle is None:
        return ctypes.get_last_error() not in SHARING_VIOLATIONS
    kernel32.CloseHandle(handle)
    return True


def is_network_path(path: Path | str) -> bool:
    """UNC path (``\\\\server\\share``) or a drive mapped to a network share. Windows only."""
    if not platform.IS_WINDOWS:
        return False
    text = os.fspath(path)
    if text.startswith(("\\\\?\\UNC\\", "//?/UNC/")):
        return True
    if text.startswith(("\\\\?\\", "//?/")):
        text = text[4:]  # \\?\C:\... is a local long path
    elif text.startswith(("\\\\", "//")):
        return True
    drive = os.path.splitdrive(text)[0]
    if len(drive) != 2 or drive[1] != ":":
        return False
    import ctypes

    drive_remote = 4
    return ctypes.windll.kernel32.GetDriveTypeW(f"{drive}\\") == drive_remote  # type: ignore[attr-defined]
