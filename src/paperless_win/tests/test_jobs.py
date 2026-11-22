"""Job objects (Windows) / process groups (elsewhere): the whole tree must die together."""

from __future__ import annotations

import shutil
import subprocess
import sys
import textwrap
import time
from typing import TYPE_CHECKING

import pytest

from paperless_win import jobs

if TYPE_CHECKING:
    from pathlib import Path

PARENT = textwrap.dedent(
    """
    import subprocess, sys, time
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    open(sys.argv[1], "w").write(str(child.pid))
    time.sleep(120)
    """,
)


def wait_for(predicate, timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.1)
    return False


def start_tree(tmp_path: Path):
    marker = tmp_path / "grandchild.pid"
    process, job = jobs.launch(
        [sys.executable, "-c", PARENT, str(marker)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    assert wait_for(lambda: marker.exists() and marker.read_text().isdigit())
    return process, job, int(marker.read_text())


def test_terminate_kills_the_child_and_its_children(tmp_path: Path) -> None:
    process, job, grandchild = start_tree(tmp_path)
    try:
        assert jobs.pid_alive(process.pid)
        assert jobs.pid_alive(grandchild)
        job.terminate()
        assert wait_for(lambda: process.poll() is not None)
        assert wait_for(lambda: not jobs.pid_alive(grandchild))
    finally:
        job.close()
        if process.poll() is None:
            process.kill()


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="KILL_ON_JOB_CLOSE is a Windows job object feature",
)
def test_closing_the_job_kills_the_tree(tmp_path: Path) -> None:
    """This is what protects against orphans when the supervisor itself dies."""
    process, job, grandchild = start_tree(tmp_path)
    job.close()
    assert wait_for(lambda: process.poll() is not None)
    assert wait_for(lambda: not jobs.pid_alive(grandchild))


def test_a_failed_launch_cleans_up() -> None:
    with pytest.raises(OSError):
        jobs.launch(["definitely-not-a-real-program-xyz"])


@pytest.mark.skipif(
    sys.platform != "win32" or shutil.which("pwsh") is None,
    reason="PowerShell 7 starts native children outside the job object (Windows only)",
)
def test_kill_tree_also_catches_children_that_escaped_the_job(tmp_path: Path) -> None:
    """``pwsh`` children are not in the job; ``kill_tree`` walks the process tree for them."""
    marker = tmp_path / "ping.txt"
    script = (
        "$p = Start-Process -FilePath ping -ArgumentList '-n','600','127.0.0.1' "
        f"-NoNewWindow -PassThru; Set-Content '{marker}' $p.Id; Start-Sleep 600"
    )
    process, job = jobs.launch(
        ["pwsh", "-NoProfile", "-Command", script],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        assert wait_for(
            lambda: marker.exists() and marker.read_text().strip().isdigit(),
        )
        ping = int(marker.read_text().strip())
        assert ping in jobs.descendants(process.pid)
        jobs.kill_tree(job, process.pid)
        assert wait_for(lambda: not jobs.pid_alive(ping))
    finally:
        job.close()
        if process.poll() is None:
            process.kill()
