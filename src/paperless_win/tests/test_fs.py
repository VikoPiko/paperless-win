from __future__ import annotations

import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from paperless_win import fs
from paperless_win import platform

windows_only = pytest.mark.skipif(
    sys.platform != "win32",
    reason="real Windows file locking",
)


def flaky(failures: int, exc: BaseException):
    state = {"calls": 0}

    def fn() -> str:
        state["calls"] += 1
        if state["calls"] <= failures:
            raise exc
        return "ok"

    return fn, state


class TestRetryIo:
    def test_runs_once_and_propagates_on_linux(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(platform, "IS_WINDOWS", False)
        fn, state = flaky(1, PermissionError("denied"))
        with pytest.raises(PermissionError):
            fs.retry_io(fn, sleep=lambda s: None)
        assert state["calls"] == 1

    def test_retries_permission_errors_on_windows(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(platform, "IS_WINDOWS", True)
        fn, state = flaky(3, PermissionError("busy"))
        delays: list[float] = []
        assert fs.retry_io(fn, sleep=delays.append, backoff=0.1) == "ok"
        assert state["calls"] == 4
        assert delays == pytest.approx([0.1, 0.2, 0.4])  # exponential

    @pytest.mark.parametrize("winerror", [32, 33])
    def test_retries_sharing_and_lock_violations(
        self,
        monkeypatch: pytest.MonkeyPatch,
        winerror: int,
    ) -> None:
        monkeypatch.setattr(platform, "IS_WINDOWS", True)
        exc = OSError(13, "busy")
        exc.winerror = winerror  # type: ignore[attr-defined]
        fn, state = flaky(1, exc)
        assert fs.retry_io(fn, sleep=lambda s: None) == "ok"
        assert state["calls"] == 2

    def test_gives_up_after_the_last_attempt(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(platform, "IS_WINDOWS", True)
        fn, state = flaky(99, PermissionError("busy"))
        with pytest.raises(PermissionError):
            fs.retry_io(fn, attempts=4, sleep=lambda s: None)
        assert state["calls"] == 4

    @pytest.mark.parametrize(
        "exc",
        [FileNotFoundError("gone"), ValueError("x"), OSError(5, "io")],
    )
    def test_other_errors_are_not_retried(
        self,
        monkeypatch: pytest.MonkeyPatch,
        exc: BaseException,
    ) -> None:
        monkeypatch.setattr(platform, "IS_WINDOWS", True)
        fn, state = flaky(1, exc)
        with pytest.raises(type(exc)):
            fs.retry_io(fn, sleep=lambda s: None)
        assert state["calls"] == 1

    def test_default_budget_is_about_five_seconds(self) -> None:
        total = sum(fs.DEFAULT_BACKOFF * 2**i for i in range(fs.DEFAULT_ATTEMPTS - 1))
        assert 4.5 <= total <= 5.5


HOLDER = textwrap.dedent(
    """
    import sys, time
    handle = open(sys.argv[1], "rb")
    print("open", flush=True)
    time.sleep(float(sys.argv[2]))
    handle.close()
    """,
)


def hold_open(path: Path, seconds: float) -> subprocess.Popen:
    proc = subprocess.Popen(
        [sys.executable, "-c", HOLDER, str(path), str(seconds)],
        stdout=subprocess.PIPE,
        text=True,
    )
    assert proc.stdout is not None
    assert proc.stdout.readline().strip() == "open"
    return proc


@windows_only
class TestRealLocks:
    def test_unlink_succeeds_after_another_process_releases(
        self,
        tmp_path: Path,
    ) -> None:
        target = tmp_path / "scan.pdf"
        target.write_bytes(b"data")
        holder = hold_open(target, 1.0)
        try:
            with pytest.raises(PermissionError):
                target.unlink()  # the lock is real
            started = time.monotonic()
            fs.retry_io(target.unlink)
            assert 0.5 < time.monotonic() - started < 4
            assert not target.exists()
        finally:
            holder.wait(timeout=10)

    def test_gives_up_when_the_lock_outlives_the_budget(self, tmp_path: Path) -> None:
        target = tmp_path / "scan.pdf"
        target.write_bytes(b"data")
        holder = hold_open(target, 3.0)
        try:
            with pytest.raises(PermissionError):
                fs.retry_io(target.unlink, attempts=3, backoff=0.05)
        finally:
            holder.wait(timeout=10)
        assert target.exists()

    def test_file_is_released_reflects_other_handles(self, tmp_path: Path) -> None:
        target = tmp_path / "scan.pdf"
        target.write_bytes(b"data")
        assert fs.file_is_released(target)
        holder = hold_open(target, 1.0)
        try:
            assert not fs.file_is_released(target)
        finally:
            holder.wait(timeout=10)
        assert fs.file_is_released(target)

    def test_file_is_released_for_missing_file(self, tmp_path: Path) -> None:
        assert fs.file_is_released(tmp_path / "missing.pdf")


class TestNetworkPaths:
    @pytest.mark.parametrize(
        "path",
        [
            "\\\\nas\\scans",
            "//nas/scans",
            "\\\\?\\UNC\\nas\\scans",
            "\\\\nas\\scans\\in\\a.pdf",
        ],
    )
    def test_unc_paths_are_network_paths(
        self,
        monkeypatch: pytest.MonkeyPatch,
        path: str,
    ) -> None:
        monkeypatch.setattr(platform, "IS_WINDOWS", True)
        assert fs.is_network_path(path)

    @pytest.mark.parametrize("path", ["relative/dir", "/posix/path", "\\\\?\\Z:\\x"])
    def test_local_looking_paths_are_not(
        self,
        monkeypatch: pytest.MonkeyPatch,
        path: str,
    ) -> None:
        monkeypatch.setattr(platform, "IS_WINDOWS", True)
        if path.startswith("\\\\?\\Z:") and sys.platform != "win32":
            pytest.skip("drive type lookup needs Windows")
        assert not fs.is_network_path(path)

    def test_never_a_network_path_on_linux(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(platform, "IS_WINDOWS", False)
        assert not fs.is_network_path("\\\\nas\\scans")
        assert fs.file_is_released(Path("anything"))

    @windows_only
    def test_local_drive_is_not_a_network_path(self, tmp_path: Path) -> None:
        assert not fs.is_network_path(tmp_path)
