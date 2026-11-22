"""Search index (tantivy) helpers for Windows. Fork-owned.

tantivy publishes a commit by replacing ``meta.json``. On Windows that replace fails with
``Access is denied (os error 5)`` while any other handle (a reader, a virus scanner, the
indexer of Windows Search) has the file open without sharing. The condition is momentary:
the commit succeeds a moment later. It showed up once in 23 runs of the 4-hour soak and
as a flaky test in the full suite, so it is retried here.

A retried ``commit()`` is safe: tantivy has already moved the added documents into its
in-memory state before it writes ``meta.json``; a second commit writes the same state.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from paperless_win import platform

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger("paperless_win.index")

ATTEMPTS = 6
BACKOFF = 0.1  # seconds, doubled each time: 0.1 + 0.2 + 0.4 + 0.8 + 1.6 = 3.1 s in all


def is_access_denied(exc: BaseException) -> bool:
    """True for tantivy's transient "Access is denied" IO error."""
    text = str(exc).lower()
    return "access is denied" in text or "os error 5" in text


def commit_with_retry(
    writer: object,
    *,
    attempts: int = ATTEMPTS,
    backoff: float = BACKOFF,
    sleep: Callable[[float], None] = time.sleep,
) -> object:
    """``writer.commit()``; on Windows retry "Access is denied" with exponential backoff.

    Anything else, and the last failure, propagates. Elsewhere it is a plain ``commit()``.
    """
    if not platform.IS_WINDOWS:
        return writer.commit()  # type: ignore[attr-defined]
    delay = backoff
    for attempt in range(1, max(attempts, 1) + 1):
        try:
            return writer.commit()  # type: ignore[attr-defined]
        except ValueError as exc:  # tantivy raises its IO errors as ValueError
            if not is_access_denied(exc) or attempt >= attempts:
                raise
            logger.warning(
                "Search index commit refused (%s), retry %d/%d in %.1fs",
                exc,
                attempt,
                attempts,
                delay,
            )
            sleep(delay)
            delay *= 2
    raise AssertionError("unreachable")  # pragma: no cover
