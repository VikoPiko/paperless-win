from __future__ import annotations

import pytest

from paperless_win import index
from paperless_win import platform

DENIED = ValueError("An IO error occurred: 'Access is denied. (os error 5)'")


class Writer:
    def __init__(self, failures: list[BaseException]) -> None:
        self.failures = list(failures)
        self.calls = 0

    def commit(self) -> int:
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)
        return 42


@pytest.fixture
def windows(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    monkeypatch.setattr(platform, "IS_WINDOWS", True)
    return []


def test_commit_succeeds_after_transient_denial(windows: list[float]) -> None:
    writer = Writer([DENIED, DENIED])
    assert index.commit_with_retry(writer, sleep=windows.append) == 42
    assert writer.calls == 3
    assert windows == [index.BACKOFF, index.BACKOFF * 2]


def test_commit_gives_up_after_the_attempts(windows: list[float]) -> None:
    writer = Writer([DENIED] * 10)
    with pytest.raises(ValueError, match="Access is denied"):
        index.commit_with_retry(writer, attempts=3, sleep=windows.append)
    assert writer.calls == 3


def test_other_errors_are_not_retried(windows: list[float]) -> None:
    writer = Writer([ValueError("schema mismatch")])
    with pytest.raises(ValueError, match="schema mismatch"):
        index.commit_with_retry(writer, sleep=windows.append)
    assert writer.calls == 1
    assert windows == []


def test_not_retried_off_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(platform, "IS_WINDOWS", False)
    writer = Writer([DENIED])
    with pytest.raises(ValueError, match="Access is denied"):
        index.commit_with_retry(writer, sleep=lambda _s: pytest.fail("slept"))
    assert writer.calls == 1


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("An IO error occurred: 'Access is denied. (os error 5)'", True),
        ("os error 5", True),
        ("disk full (os error 112)", False),
    ],
)
def test_is_access_denied(message: str, *, expected: bool) -> None:
    assert index.is_access_denied(ValueError(message)) is expected
