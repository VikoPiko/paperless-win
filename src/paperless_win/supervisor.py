"""Process supervisor: the Windows replacement for s6-overlay.

The engine here knows nothing about paperless. It starts a list of ``ChildSpec`` in order,
restarts crashed children with exponential backoff (and gives up on a crash loop), kills
workers whose task ran past its time limit, and shuts everything down in a sensible order.
``paperless_win.stack`` decides *which* children paperless needs.

Everything that touches the operating system (spawning, clocks, sleeping) is injected, so
the unit tests drive the whole thing with fake processes and a fake clock, on any OS.

Files under ``run_dir`` (all small JSON or marker files):

* ``w<i>.json``   written by worker i while a task runs: ``{task_id, task_name, started_at}``
* ``w<i>.stop``   created by the supervisor to ask worker i to exit after its current task
* ``state.json``  written by the supervisor for ``paperless-ctl status``
* ``supervisor.stop``  created by ``paperless-ctl stop`` to ask the supervisor to shut down
"""

from __future__ import annotations

import contextlib
import json
import logging
import logging.handlers
import os
import re
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass
from dataclasses import field
from typing import TYPE_CHECKING
from typing import Protocol

from paperless_win import jobs

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

logger = logging.getLogger("paperless.winport.supervisor")

STATE_FILE = "state.json"
STOP_REQUEST_FILE = "supervisor.stop"
_WORKER_FILE = re.compile(r"^w(\d+)\.json$")

# Child lifecycle states
STARTING, RUNNING, BACKOFF, FAILED, STOPPED = (
    "starting",
    "running",
    "backoff",
    "failed",
    "stopped",
)

# Stop order: front ends first (no new work), then workers (finish what they are doing),
# then the broker they talk to.
PHASE_FRONT, PHASE_WORKER, PHASE_BROKER = 0, 1, 2


def human_duration(seconds: float) -> str:
    """``45 seconds`` / ``30 minutes``, for log lines and the failure shown in the web UI."""
    seconds = round(seconds)
    if seconds < 120:
        return f"{seconds} seconds"
    return f"{round(seconds / 60)} minutes"


class SupervisorError(RuntimeError):
    """The stack could not be started."""


class ProcessLike(Protocol):
    pid: int

    def poll(self) -> int | None: ...
    def terminate_tree(self) -> None: ...


@dataclass(frozen=True)
class ChildSpec:
    name: str
    argv: list[str]
    cwd: Path
    env: dict[str, str] = field(default_factory=dict)
    # Called until it returns True before the next child is started (Garnet's PING).
    ready: Callable[[], bool] | None = None
    ready_timeout: float = 30.0
    # Do not start until this long after the supervisor started (flower).
    start_delay: float = 0.0
    # Exit code 0 is the expected way to end (worker recycling), not a crash.
    restart_on_clean_exit: bool = False
    worker_index: int | None = None
    stop_phase: int = PHASE_FRONT


@dataclass(frozen=True)
class RestartPolicy:
    """Exponential backoff per child, and give up on a crash loop."""

    base_delay: float = 1.0
    max_delay: float = 30.0
    stable_after: float = 60.0  # running this long resets the backoff
    max_crashes: int = 5
    window: float = 180.0  # ... within this many seconds means "crash loop"
    min_clean_run: float = 2.0  # a "clean" exit sooner than this is a crash

    def delay(self, consecutive: int) -> float:
        return min(self.base_delay * (2 ** max(consecutive - 1, 0)), self.max_delay)


@dataclass
class ChildRuntime:
    spec: ChildSpec
    process: ProcessLike | None = None
    state: str = STARTING
    started_at: float = 0.0  # monotonic
    started_wall: float = 0.0
    restart_at: float = 0.0
    restarts: int = 0
    consecutive: int = 0
    crashes: deque = field(default_factory=deque)
    last_exit: int | None = None
    expected_exit: bool = False  # we killed it on purpose (watchdog)

    def describe(self, now: float, wall: float) -> dict:
        up = (
            max(now - self.started_at, 0.0)
            if self.state == RUNNING and self.process
            else 0.0
        )
        return {
            "name": self.spec.name,
            "state": self.state,
            "pid": self.process.pid if self.process else None,
            "uptime_seconds": round(up, 1),
            "restarts": self.restarts,
            "last_exit": self.last_exit,
            "started_at": self.started_wall if self.process else None,
            "updated_at": wall,
        }


class Watchdog:
    """Finds workers whose current task has run longer than the time limit.

    Celery's solo pool cannot enforce ``task_time_limit`` itself, so each worker records
    its running task in ``run_dir/w<i>.json`` and we compare against the wall clock here.
    """

    def __init__(
        self,
        run_dir: Path,
        limit_seconds: float,
        grace_seconds: float = 30.0,
        wall: Callable[[], float] = time.time,
    ) -> None:
        self.run_dir = run_dir
        self.limit = limit_seconds
        self.grace = grace_seconds
        self.wall = wall

    def _entries(self) -> list[tuple[int, Path, dict | None]]:
        entries = []
        for path in sorted(self.run_dir.glob("w*.json")):
            match = _WORKER_FILE.match(path.name)
            if not match:
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = None  # being written right now, or garbage: look again next time
            entries.append((int(match.group(1)), path, data))
        return entries

    def overdue(self) -> list[tuple[int, Path, dict]]:
        """``(worker_index, file, record)`` for every task past limit + grace."""
        if self.limit <= 0:
            return []
        now = self.wall()
        found = []
        for index, path, data in self._entries():
            if not isinstance(data, dict):
                continue
            try:
                started = float(data["started_at"])
            except (KeyError, TypeError, ValueError):
                continue
            if now - started > self.limit + self.grace:
                found.append((index, path, data))
        return found

    def leftovers(self) -> list[tuple[int, Path, dict | None]]:
        """Task files that exist at startup: those tasks died with the previous supervisor."""
        return self._entries()

    def is_busy(self, index: int) -> bool:
        return (self.run_dir / f"w{index}.json").exists()


class ChildLogs:
    """Rotating log files: one per child plus a combined ``supervisor.log``."""

    def __init__(
        self,
        log_dir: Path,
        max_bytes: int = 10 * 1024 * 1024,
        backups: int = 5,
    ) -> None:
        self.log_dir = log_dir
        self.max_bytes = max_bytes
        self.backups = backups
        self._children: dict[str, logging.Logger] = {}
        self._lock = threading.Lock()
        log_dir.mkdir(parents=True, exist_ok=True)
        self._combined = self._make(
            "winport.combined",
            "supervisor.log",
            "%(asctime)s %(message)s",
        )

    def _make(self, name: str, filename: str, fmt: str) -> logging.Logger:
        log = logging.getLogger(f"{name}.{id(self)}")
        log.setLevel(logging.INFO)
        log.propagate = False
        handler = logging.handlers.RotatingFileHandler(
            self.log_dir / filename,
            maxBytes=self.max_bytes,
            backupCount=self.backups,
            encoding="utf-8",
            delay=True,
        )
        handler.setFormatter(logging.Formatter(fmt))
        log.addHandler(handler)
        return log

    def line(self, child: str, text: str) -> None:
        with self._lock:
            own = self._children.get(child)
            if own is None:
                own = self._children[child] = self._make(
                    f"winport.child.{child}",
                    f"{child}.log",
                    "%(message)s",
                )
        own.info(text)
        self._combined.info("[%s] %s", child, text)

    def event(self, text: str) -> None:
        self._combined.info("[supervisor] %s", text)

    def close(self) -> None:
        for log in (*self._children.values(), self._combined):
            for handler in list(log.handlers):
                handler.close()
                log.removeHandler(handler)


class ManagedProcess:
    """A real child: started in its own job object, output pumped into ``ChildLogs``."""

    def __init__(self, spec: ChildSpec, env: dict[str, str], logs: ChildLogs) -> None:
        self.spec = spec
        self._logs = logs
        self._closed = False
        self._popen, self._job = jobs.launch(
            spec.argv,
            cwd=str(spec.cwd),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        self.pid = self._popen.pid
        self._pump = threading.Thread(
            target=self._pump_output,
            name=f"log-{spec.name}",
            daemon=True,
        )
        self._pump.start()

    def _pump_output(self) -> None:
        stream = self._popen.stdout
        if stream is None:  # pragma: no cover
            return
        try:
            for raw in iter(stream.readline, b""):
                self._logs.line(
                    self.spec.name,
                    raw.decode("utf-8", errors="replace").rstrip("\r\n"),
                )
        except (OSError, ValueError):  # pipe closed under us while stopping
            pass

    def poll(self) -> int | None:
        code = self._popen.poll()
        if code is not None and not self._closed:
            # The main process is gone. Take anything it left behind (tesseract, gs) with it.
            self._closed = True
            self._job.terminate()
            self._job.close()
        return code

    def terminate_tree(self) -> None:
        jobs.kill_tree(self._job, self.pid)

    def wait(self, timeout: float) -> int | None:
        try:
            return self._popen.wait(timeout)
        except subprocess.TimeoutExpired:
            return None


class Supervisor:
    def __init__(
        self,
        specs: list[ChildSpec],
        spawn: Callable[[ChildSpec], ProcessLike],
        *,
        run_dir: Path,
        policy: RestartPolicy | None = None,
        watchdog: Watchdog | None = None,
        fail_task: Callable[[str, str], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
        wall: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
        events: Callable[[str], None] | None = None,
        state_interval: float = 2.0,
    ) -> None:
        self.runtimes = [ChildRuntime(spec) for spec in specs]
        self.spawn = spawn
        self.run_dir = run_dir
        self.policy = policy or RestartPolicy()
        self.watchdog = watchdog
        self.fail_task = fail_task or (lambda task_id, reason: None)
        self.clock = clock
        self.wall = wall
        self.sleep = sleep
        self._events = events or (lambda text: logger.info(text))
        self.state_interval = state_interval
        self.fatal: str | None = None
        self._last_state = float("-inf")
        self._began = 0.0

    # -- helpers --------------------------------------------------------------------------
    def log(self, text: str) -> None:
        self._events(text)

    def _by_worker(self, index: int) -> ChildRuntime | None:
        for rt in self.runtimes:
            if rt.spec.worker_index == index:
                return rt
        return None

    def _start(self, rt: ChildRuntime) -> None:
        now = self.clock()
        try:
            rt.process = self.spawn(rt.spec)
        except Exception as exc:
            rt.process = None
            self.log(f"{rt.spec.name}: could not start: {exc}")
            self._after_exit(rt, exit_code=-1, ran_for=0.0, now=now)
            return
        rt.state = RUNNING
        rt.started_at = now
        rt.started_wall = self.wall()
        rt.expected_exit = False
        self.log(f"{rt.spec.name}: started (pid {rt.process.pid})")

    def _wait_ready(self, rt: ChildRuntime) -> None:
        spec = rt.spec
        if spec.ready is None:
            return
        deadline = self.clock() + spec.ready_timeout
        while not spec.ready():
            if rt.process is None or rt.process.poll() is not None:
                code = rt.process.poll() if rt.process else None
                raise SupervisorError(
                    f"{spec.name} exited during startup (code {code}). "
                    f"See {spec.name}.log in the log folder.",
                )
            if self.clock() >= deadline:
                raise SupervisorError(
                    f"{spec.name} was not ready after {spec.ready_timeout:.0f} s",
                )
            self.sleep(0.2)
        # Something answered. Make sure it is our child: if the port was taken by another server
        # the child dies a moment later, and carrying on would hide that.
        self.sleep(0.5)
        if rt.process is not None and rt.process.poll() is not None:
            code = rt.process.poll()
            raise SupervisorError(
                f"{spec.name} exited (code {code}) although something answers where it should "
                "listen: is another server already using that port? Stop it, change the port "
                "(PAPERLESS_REDIS), or set PAPERLESS_WIN_BROKER=external to use the other server.",
            )
        self.log(f"{spec.name}: ready")

    # -- lifecycle ------------------------------------------------------------------------
    def start_all(self) -> None:
        """Start every child in order. Raises ``SupervisorError`` if a gate is never reached."""
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self._began = self.clock()
        self._reconcile_leftovers()
        for stale in self.run_dir.glob("w*.stop"):
            stale.unlink(missing_ok=True)
        (self.run_dir / STOP_REQUEST_FILE).unlink(missing_ok=True)
        for rt in self.runtimes:
            if rt.spec.start_delay > 0:
                rt.state = BACKOFF
                rt.restart_at = self._began + rt.spec.start_delay
                continue
            self._start(rt)
            if rt.state == RUNNING:
                self._wait_ready(rt)
            elif rt.spec.ready is not None or rt.state == FAILED:
                raise SupervisorError(f"{rt.spec.name} could not be started")
        self.write_state(force=True)

    def _reconcile_leftovers(self) -> None:
        """Tasks that were running when the previous supervisor died will never finish."""
        if not self.watchdog:
            return
        for index, path, data in self.watchdog.leftovers():
            task_id = data.get("task_id") if isinstance(data, dict) else None
            if task_id:
                self.log(f"w{index}: task {task_id} was interrupted by a restart")
                self.fail_task(
                    str(task_id),
                    "The task was interrupted because paperless-win was stopped or restarted.",
                )
            path.unlink(missing_ok=True)

    def tick(self) -> None:
        now = self.clock()
        for rt in self.runtimes:
            if rt.state == RUNNING and rt.process is not None:
                code = rt.process.poll()
                if code is not None:
                    self._after_exit(
                        rt,
                        exit_code=code,
                        ran_for=now - rt.started_at,
                        now=now,
                    )
        for rt in self.runtimes:
            if rt.state == BACKOFF and now >= rt.restart_at:
                self._start(rt)
        self._check_watchdog()
        self.write_state()

    def _after_exit(
        self,
        rt: ChildRuntime,
        *,
        exit_code: int,
        ran_for: float,
        now: float,
    ) -> None:
        spec, policy = rt.spec, self.policy
        rt.last_exit = exit_code
        rt.process = None
        if ran_for >= policy.stable_after:
            rt.consecutive = 0
            rt.crashes.clear()

        clean = exit_code == 0 and spec.restart_on_clean_exit
        if (clean and ran_for >= policy.min_clean_run) or rt.expected_exit:
            what = "killed by the watchdog" if rt.expected_exit else "recycled"
            self.log(f"{spec.name}: {what}, restarting")
            rt.restarts += 1
            rt.state = BACKOFF
            rt.restart_at = now
            rt.expected_exit = False
            return

        rt.crashes.append(now)
        while rt.crashes and now - rt.crashes[0] > policy.window:
            rt.crashes.popleft()
        rt.consecutive += 1
        if len(rt.crashes) >= policy.max_crashes:
            rt.state = FAILED
            self.fatal = (
                f"{spec.name} crashed {len(rt.crashes)} times within "
                f"{policy.window:.0f} s (last exit code {exit_code}); giving up. "
                f"See the {spec.name}.log file in the log folder."
            )
            self.log(self.fatal)
            return
        delay = policy.delay(rt.consecutive)
        rt.restarts += 1
        rt.state = BACKOFF
        rt.restart_at = now + delay
        self.log(
            f"{spec.name}: exited with code {exit_code} after {ran_for:.1f} s; "
            f"restarting in {delay:.1f} s (crash {len(rt.crashes)}/{policy.max_crashes})",
        )

    def _check_watchdog(self) -> None:
        if not self.watchdog:
            return
        for index, path, record in self.watchdog.overdue():
            rt = self._by_worker(index)
            task_id = str(record.get("task_id", ""))
            name = record.get("task_name", "task")
            started = float(record["started_at"])
            ran = human_duration(self.wall() - started)
            limit = human_duration(self.watchdog.limit)
            self.log(
                f"w{index}: {name} {task_id} has run for {ran}, over the {limit} limit: "
                "killing the worker and its children",
            )
            if rt is not None and rt.process is not None:
                rt.expected_exit = True
                rt.process.terminate_tree()
            path.unlink(missing_ok=True)
            if task_id:
                self.fail_task(
                    task_id,
                    f"The task ran longer than the time limit of {limit} "
                    "and was stopped by the supervisor.",
                )

    def write_state(self, *, force: bool = False) -> None:
        now = self.clock()
        if not force and now - self._last_state < self.state_interval:
            return
        self._last_state = now
        wall = self.wall()
        data = {
            "supervisor_pid": os.getpid(),
            "started_at": wall - (now - self._began),
            "updated_at": wall,
            "stopping": self.fatal is not None,
            "children": [rt.describe(now, wall) for rt in self.runtimes],
        }
        target = self.run_dir / STATE_FILE
        tmp = target.with_suffix(".tmp")
        with contextlib.suppress(OSError):
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            tmp.replace(target)

    # -- running and stopping -------------------------------------------------------------
    def stop_requested(self) -> bool:
        return (self.run_dir / STOP_REQUEST_FILE).exists()

    def run(
        self,
        should_stop: Callable[[], bool] = lambda: False,
        stop_timeout: float = 10.0,
    ) -> int:
        """Start everything and supervise until asked to stop. Returns the exit code."""
        try:
            self.start_all()
        except SupervisorError as exc:
            self.log(f"startup failed: {exc}")
            self.shutdown(timeout=5.0)
            return 1
        while not (should_stop() or self.stop_requested() or self.fatal):
            self.tick()
            self.sleep(0.5)
        self.shutdown(timeout=stop_timeout)
        return 1 if self.fatal else 0

    def shutdown(self, timeout: float = 10.0) -> None:
        """Stop everything within roughly ``timeout`` seconds, in dependency order."""
        deadline = self.clock() + timeout
        self.log("stopping")
        for rt in self.runtimes:
            rt.state = rt.state if rt.state == FAILED else STOPPED
        # 1. front ends: nothing new comes in
        for rt in self.runtimes:
            if rt.spec.stop_phase == PHASE_FRONT:
                self._kill(rt)
        # 2. workers finish their current task, up to the deadline
        workers = [rt for rt in self.runtimes if rt.spec.stop_phase == PHASE_WORKER]
        for rt in workers:
            if rt.spec.worker_index is not None and rt.process is not None:
                (self.run_dir / f"w{rt.spec.worker_index}.stop").write_text("stop")
        broker_budget = 1.0
        while self.clock() < deadline - broker_budget and any(
            rt.process is not None and rt.process.poll() is None for rt in workers
        ):
            self.sleep(0.2)
        for rt in workers:
            self._kill(rt)
        # 3. the broker last
        for rt in self.runtimes:
            if rt.spec.stop_phase == PHASE_BROKER:
                self._kill(rt)
        for leftover in self.run_dir.glob("w*.stop"):
            leftover.unlink(missing_ok=True)
        # a worker killed mid-task leaves its file behind: next start marks that task failed
        self.write_state(force=True)
        self.log("stopped")

    def _kill(self, rt: ChildRuntime) -> None:
        process = rt.process
        if process is None:
            return
        if process.poll() is None:
            process.terminate_tree()
            for _ in range(50):  # up to 5 s for the OS to reap it
                if process.poll() is not None:
                    break
                self.sleep(0.1)
        rt.process = None
