"""Supervisor engine tests: fake processes, fake clock. Run on every OS."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from paperless_win.supervisor import BACKOFF
from paperless_win.supervisor import FAILED
from paperless_win.supervisor import PHASE_BROKER
from paperless_win.supervisor import PHASE_FRONT
from paperless_win.supervisor import PHASE_WORKER
from paperless_win.supervisor import RUNNING
from paperless_win.supervisor import ChildSpec
from paperless_win.supervisor import RestartPolicy
from paperless_win.supervisor import Supervisor
from paperless_win.supervisor import SupervisorError
from paperless_win.supervisor import Watchdog


class FakeProcess:
    _next_pid = 1000

    def __init__(self, spec: ChildSpec) -> None:
        FakeProcess._next_pid += 1
        self.pid = FakeProcess._next_pid
        self.spec = spec
        self.code: int | None = None
        self.killed = False

    def poll(self) -> int | None:
        return self.code

    def terminate_tree(self) -> None:
        self.killed = True
        self.code = 1

    def exit(self, code: int) -> None:
        self.code = code


class Harness:
    """A supervisor wired to a fake clock, fake processes and a recording log."""

    def __init__(self, run_dir: Path, specs: list[ChildSpec], **kwargs) -> None:
        self.now = 0.0
        self.wall = 1_000_000.0
        self.spawned: list[FakeProcess] = []
        self.events: list[str] = []
        self.failed_tasks: list[tuple[str, str]] = []
        self.on_sleep = lambda: None

        def spawn(spec: ChildSpec) -> FakeProcess:
            process = FakeProcess(spec)
            self.spawned.append(process)
            return process

        def sleep(seconds: float) -> None:
            self.now += seconds
            self.wall += seconds
            self.on_sleep()

        self.supervisor = Supervisor(
            specs,
            spawn,
            run_dir=run_dir,
            clock=lambda: self.now,
            wall=lambda: self.wall,
            sleep=sleep,
            events=self.events.append,
            fail_task=lambda task_id, reason: self.failed_tasks.append(
                (task_id, reason),
            ),
            state_interval=0,
            **kwargs,
        )

    def advance(self, seconds: float) -> None:
        self.now += seconds
        self.wall += seconds

    def processes(self, name: str) -> list[FakeProcess]:
        return [p for p in self.spawned if p.spec.name == name]

    def runtime(self, name: str):
        return next(rt for rt in self.supervisor.runtimes if rt.spec.name == name)


def spec(name: str, **kwargs) -> ChildSpec:
    return ChildSpec(name=name, argv=[name], cwd=Path(), **kwargs)


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    return tmp_path / "run"


def test_children_start_in_the_given_order(run_dir: Path) -> None:
    h = Harness(run_dir, [spec("garnet"), spec("web"), spec("worker1")])
    h.supervisor.start_all()
    assert [p.spec.name for p in h.spawned] == ["garnet", "web", "worker1"]
    assert all(rt.state == RUNNING for rt in h.supervisor.runtimes)


def test_next_child_waits_until_the_gate_opens(run_dir: Path) -> None:
    gate = {"open": False}
    h = Harness(
        run_dir,
        [spec("garnet", ready=lambda: gate["open"]), spec("web")],
    )
    h.on_sleep = lambda: gate.update(open=h.now >= 1.0)
    h.supervisor.start_all()
    assert h.now >= 1.0
    assert [p.spec.name for p in h.spawned] == ["garnet", "web"]


def test_startup_fails_if_the_gate_never_opens(run_dir: Path) -> None:
    h = Harness(
        run_dir,
        [spec("garnet", ready=lambda: False, ready_timeout=3), spec("web")],
    )
    with pytest.raises(SupervisorError, match="garnet was not ready"):
        h.supervisor.start_all()
    assert [p.spec.name for p in h.spawned] == ["garnet"]


def test_startup_fails_if_the_gated_child_dies(run_dir: Path) -> None:
    h = Harness(run_dir, [spec("garnet", ready=lambda: False)])
    h.on_sleep = lambda: h.spawned[0].exit(3)
    with pytest.raises(SupervisorError, match="exited during startup"):
        h.supervisor.start_all()


def test_a_crashed_child_is_restarted_with_growing_delay(run_dir: Path) -> None:
    h = Harness(run_dir, [spec("web")])
    h.supervisor.start_all()
    delays = []
    for _ in range(3):
        h.processes("web")[-1].exit(1)
        before = h.now
        h.supervisor.tick()
        rt = h.runtime("web")
        assert rt.state == BACKOFF
        delays.append(rt.restart_at - before)
        h.advance(rt.restart_at - h.now)
        h.supervisor.tick()
        assert rt.state == RUNNING
    assert delays == [1.0, 2.0, 4.0]
    assert h.runtime("web").restarts == 3


def test_backoff_is_capped(run_dir: Path) -> None:
    policy = RestartPolicy(max_delay=5.0, max_crashes=100)
    assert [policy.delay(n) for n in (1, 2, 3, 4, 5, 9)] == [1, 2, 4, 5, 5, 5]


def test_backoff_resets_after_a_stable_run(run_dir: Path) -> None:
    h = Harness(run_dir, [spec("web")])
    h.supervisor.start_all()
    for _ in range(2):
        h.processes("web")[-1].exit(1)
        h.supervisor.tick()
        h.advance(h.runtime("web").restart_at - h.now)
        h.supervisor.tick()
    h.advance(120)  # ran well past stable_after
    h.processes("web")[-1].exit(1)
    before = h.now
    h.supervisor.tick()
    assert h.runtime("web").restart_at - before == 1.0
    assert h.supervisor.fatal is None


def test_a_crash_loop_makes_the_supervisor_give_up_with_a_clear_message(
    run_dir: Path,
) -> None:
    h = Harness(
        run_dir,
        [spec("web")],
        policy=RestartPolicy(max_crashes=3, base_delay=0.1),
    )
    h.supervisor.start_all()
    for _ in range(3):
        h.processes("web")[-1].exit(1)
        h.supervisor.tick()
        h.advance(1)
        h.supervisor.tick()
    assert h.runtime("web").state == FAILED
    assert h.supervisor.fatal is not None
    assert "web crashed 3 times" in h.supervisor.fatal
    assert "giving up" in h.supervisor.fatal


def test_crashes_outside_the_window_do_not_add_up(run_dir: Path) -> None:
    h = Harness(
        run_dir,
        [spec("web")],
        policy=RestartPolicy(
            max_crashes=2,
            window=10,
            stable_after=1000,
            base_delay=0.1,
        ),
    )
    h.supervisor.start_all()
    for _ in range(4):
        h.processes("web")[-1].exit(1)
        h.supervisor.tick()
        h.advance(30)
        h.supervisor.tick()
    assert h.supervisor.fatal is None


def test_clean_exit_of_a_worker_is_a_recycle_not_a_crash(run_dir: Path) -> None:
    h = Harness(run_dir, [spec("worker1", restart_on_clean_exit=True)])
    h.supervisor.start_all()
    for _ in range(10):  # far more than max_crashes
        h.advance(8)  # a worker takes a few seconds to come up and do a task
        h.processes("worker1")[-1].exit(0)
        h.supervisor.tick()
        h.supervisor.tick()
    assert h.supervisor.fatal is None
    assert len(h.processes("worker1")) == 11
    assert h.runtime("worker1").restarts == 10


def test_clean_exit_right_after_start_counts_as_a_crash(run_dir: Path) -> None:
    h = Harness(
        run_dir,
        [spec("worker1", restart_on_clean_exit=True)],
        policy=RestartPolicy(max_crashes=3, base_delay=0.1),
    )
    h.supervisor.start_all()
    for _ in range(3):
        h.processes("worker1")[-1].exit(0)  # instantly: a hot restart loop
        h.supervisor.tick()
        h.advance(1)
        h.supervisor.tick()
    assert h.supervisor.fatal is not None


def test_clean_exit_of_a_service_is_restarted_as_a_crash(run_dir: Path) -> None:
    h = Harness(run_dir, [spec("web")])
    h.supervisor.start_all()
    h.advance(10)
    h.processes("web")[-1].exit(0)
    h.supervisor.tick()
    assert h.runtime("web").state == BACKOFF
    assert len(h.runtime("web").crashes) == 1


def test_a_child_that_cannot_be_started_is_retried(run_dir: Path) -> None:
    attempts = {"n": 0}
    h = Harness(run_dir, [spec("web")])

    def flaky(s: ChildSpec) -> FakeProcess:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise FileNotFoundError("python.exe")
        return FakeProcess(s)

    h.supervisor.spawn = flaky
    h.supervisor.start_all()  # not gated: first failure is only logged
    assert h.runtime("web").state == BACKOFF
    for _ in range(2):
        h.advance(h.runtime("web").restart_at - h.now)
        h.supervisor.tick()
    assert h.runtime("web").state == RUNNING
    assert any("could not start" in e for e in h.events)


def test_delayed_child_starts_after_its_delay(run_dir: Path) -> None:
    h = Harness(run_dir, [spec("web"), spec("flower", start_delay=5)])
    h.supervisor.start_all()
    assert not h.processes("flower")
    h.advance(4)
    h.supervisor.tick()
    assert not h.processes("flower")
    h.advance(2)
    h.supervisor.tick()
    assert len(h.processes("flower")) == 1


# -- watchdog -------------------------------------------------------------------------------
def write_task(run_dir: Path, index: int, task_id: str, started_at: float) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / f"w{index}.json"
    path.write_text(
        json.dumps(
            {"task_id": task_id, "task_name": "consume_file", "started_at": started_at},
        ),
    )
    return path


def watchdog_harness(run_dir: Path, limit: float = 100) -> Harness:
    specs = [
        spec(
            "worker1",
            worker_index=1,
            restart_on_clean_exit=True,
            stop_phase=PHASE_WORKER,
        ),
    ]
    h = Harness(run_dir, specs)
    h.supervisor.watchdog = Watchdog(
        run_dir,
        limit,
        grace_seconds=10,
        wall=lambda: h.wall,
    )
    return h


def test_watchdog_leaves_a_task_inside_its_limit_alone(run_dir: Path) -> None:
    h = watchdog_harness(run_dir)
    h.supervisor.start_all()
    write_task(run_dir, 1, "t1", h.wall - 50)
    h.supervisor.tick()
    assert not h.processes("worker1")[0].killed


def test_watchdog_kills_the_worker_tree_and_fails_the_task(run_dir: Path) -> None:
    h = watchdog_harness(run_dir)
    h.supervisor.start_all()
    record = write_task(run_dir, 1, "t1", h.wall - 111)  # past limit + grace
    h.supervisor.tick()
    first = h.processes("worker1")[0]
    assert first.killed
    assert not record.exists()
    assert [t for t, _ in h.failed_tasks] == ["t1"]
    assert "time limit" in h.failed_tasks[0][1]
    # the next tick sees the exit and brings a new worker up at once, without counting a crash
    h.supervisor.tick()
    assert len(h.processes("worker1")) == 2
    assert not h.runtime("worker1").crashes


def test_watchdog_ignores_half_written_files(run_dir: Path) -> None:
    h = watchdog_harness(run_dir)
    h.supervisor.start_all()
    (run_dir / "w1.json").write_text("{not json")
    h.supervisor.tick()
    assert not h.processes("worker1")[0].killed


def test_watchdog_disabled_with_zero_limit(run_dir: Path) -> None:
    h = watchdog_harness(run_dir, limit=0)
    h.supervisor.start_all()
    write_task(run_dir, 1, "t1", h.wall - 10_000)
    h.supervisor.tick()
    assert not h.processes("worker1")[0].killed


def test_tasks_left_by_a_previous_run_are_marked_failed_at_startup(
    run_dir: Path,
) -> None:
    h = watchdog_harness(run_dir)
    write_task(run_dir, 1, "old-task", h.wall - 5)
    h.supervisor.start_all()
    assert [t for t, _ in h.failed_tasks] == ["old-task"]
    assert "interrupted" in h.failed_tasks[0][1]
    assert not (run_dir / "w1.json").exists()


# -- stopping -------------------------------------------------------------------------------
def stack_specs() -> list[ChildSpec]:
    return [
        spec("garnet", stop_phase=PHASE_BROKER),
        spec("web", stop_phase=PHASE_FRONT),
        spec(
            "worker1",
            worker_index=1,
            stop_phase=PHASE_WORKER,
            restart_on_clean_exit=True,
        ),
    ]


def test_shutdown_stops_front_ends_then_workers_then_the_broker(run_dir: Path) -> None:
    h = Harness(run_dir, stack_specs())
    h.supervisor.start_all()
    order: list[str] = []
    for p in h.spawned:
        original = p.terminate_tree
        p.terminate_tree = lambda original=original, name=p.spec.name: (
            order.append(name),
            original(),
        )[1]

    def worker_exits_when_asked() -> None:
        if (run_dir / "w1.stop").exists():
            h.processes("worker1")[0].exit(0)

    h.on_sleep = worker_exits_when_asked
    h.supervisor.shutdown(timeout=15)
    assert order[0] == "web"
    assert order[-1] == "garnet"
    assert "worker1" not in order  # it left by itself after the stop request
    assert not list(run_dir.glob("w*.stop"))


def test_shutdown_kills_a_worker_that_does_not_finish_in_time(run_dir: Path) -> None:
    h = Harness(run_dir, stack_specs())
    h.supervisor.start_all()
    h.supervisor.shutdown(timeout=5)
    assert h.processes("worker1")[0].killed
    assert h.processes("garnet")[0].killed
    assert h.now <= 8  # stayed close to the budget


def test_shutdown_leaves_the_interrupted_tasks_file_for_the_next_start(
    run_dir: Path,
) -> None:
    h = watchdog_harness(run_dir)
    h.supervisor.start_all()
    write_task(run_dir, 1, "busy", h.wall)
    h.supervisor.shutdown(timeout=3)
    assert (run_dir / "w1.json").exists()


def test_run_returns_zero_on_a_requested_stop_and_one_after_giving_up(
    run_dir: Path,
) -> None:
    h = Harness(run_dir, stack_specs())
    calls = {"n": 0}

    def stop_after_three() -> bool:
        calls["n"] += 1
        return calls["n"] > 3

    assert h.supervisor.run(stop_after_three) == 0

    h2 = Harness(run_dir, [spec("web")], policy=RestartPolicy(max_crashes=1))
    h2.on_sleep = lambda: h2.spawned[-1].exit(1)
    assert h2.supervisor.run() == 1


def test_stop_request_file_ends_the_run(run_dir: Path) -> None:
    h = Harness(run_dir, stack_specs())
    h.on_sleep = lambda: (run_dir / "supervisor.stop").write_text("stop")
    assert h.supervisor.run() == 0
    assert all(p.killed or p.code is not None for p in h.spawned)


def test_stale_stop_files_from_a_crash_do_not_stop_the_new_workers(
    run_dir: Path,
) -> None:
    run_dir.mkdir(parents=True)
    (run_dir / "w1.stop").write_text("stop")
    (run_dir / "supervisor.stop").write_text("stop")
    h = Harness(run_dir, stack_specs())
    h.supervisor.start_all()
    assert not (run_dir / "w1.stop").exists()
    assert not h.supervisor.stop_requested()


def test_state_file_describes_every_child(run_dir: Path) -> None:
    h = Harness(run_dir, stack_specs())
    h.supervisor.start_all()
    h.advance(65)
    h.supervisor.tick()
    state = json.loads((run_dir / "state.json").read_text())
    names = [c["name"] for c in state["children"]]
    assert names == ["garnet", "web", "worker1"]
    web = state["children"][1]
    assert web["state"] == "running"
    assert web["pid"] == h.processes("web")[0].pid
    assert web["uptime_seconds"] == pytest.approx(65, abs=1)
