"""Stack definition, worker-side signals and CLI helpers."""

from __future__ import annotations

import json
import socket
import threading
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from paperless_win import celery_signals
from paperless_win import ctl
from paperless_win import jobs
from paperless_win import stack
from paperless_win.supervisor import PHASE_BROKER
from paperless_win.supervisor import PHASE_FRONT
from paperless_win.supervisor import PHASE_WORKER

if TYPE_CHECKING:
    from pathlib import Path


def config(tmp_path: Path, **overrides) -> stack.StackConfig:
    values = {
        "python": "py.exe",
        "src": tmp_path / "src",
        "run_dir": tmp_path / "run",
        "log_dir": tmp_path / "logs",
        "redis_url": "redis://127.0.0.1:6379",
        "task_workers": 2,
        "time_limit": 1800,
        "recycle_after": 1,
        "consumer_disabled": False,
        "flower": False,
        "garnet": "C:/tools/GarnetServer.exe",
    }
    values.update(overrides)
    return stack.StackConfig(**values)


def names(specs) -> list[str]:
    return [s.name for s in specs]


def test_default_stack_matches_the_s6_services(tmp_path: Path) -> None:
    specs = stack.build_specs(config(tmp_path), {})
    assert names(specs) == ["garnet", "web", "beat", "consumer", "worker1", "worker2"]


def test_workers_are_celery_solo_with_their_own_node_name(tmp_path: Path) -> None:
    worker = stack.build_specs(config(tmp_path), {})[-1]
    assert worker.argv[:3] == ["py.exe", "-m", "celery"]
    assert "solo" in worker.argv
    assert "w2@%h" in worker.argv
    assert "--without-mingle" in worker.argv
    assert "--without-gossip" in worker.argv
    assert worker.restart_on_clean_exit
    assert worker.worker_index == 2
    assert worker.env["PAPERLESS_WIN_WORKER_INDEX"] == "2"
    assert worker.stop_phase == PHASE_WORKER


def test_web_uses_granian_with_the_asyncio_loop(tmp_path: Path) -> None:
    web = stack.build_specs(config(tmp_path), {})[1]
    assert web.argv[2] == "granian"
    assert web.argv[web.argv.index("--loop") + 1] == "asyncio"
    assert web.stop_phase == PHASE_FRONT


def test_consumer_can_be_disabled(tmp_path: Path) -> None:
    specs = stack.build_specs(config(tmp_path, consumer_disabled=True), {})
    assert "consumer" not in names(specs)


def test_flower_is_optional_and_delayed(tmp_path: Path) -> None:
    assert "flower" not in names(stack.build_specs(config(tmp_path), {}))
    flower = stack.build_specs(config(tmp_path, flower=True), {})[-1]
    assert flower.name == "flower"
    assert flower.start_delay > 0


def test_garnet_is_started_only_for_a_local_broker(tmp_path: Path) -> None:
    assert names(stack.build_specs(config(tmp_path), {}))[0] == "garnet"
    remote = config(tmp_path, redis_url="redis://cache.example:6379", garnet=None)
    assert "garnet" not in names(stack.build_specs(remote, {}))


def test_missing_garnet_is_a_clear_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Garnet"):
        stack.build_specs(config(tmp_path, garnet=None), {})


def test_garnet_binds_the_configured_loopback_port(tmp_path: Path) -> None:
    garnet = stack.build_specs(
        config(tmp_path, redis_url="redis://localhost:6390"),
        {},
    )[0]
    assert garnet.argv[1:] == ["--bind", "127.0.0.1", "--port", "6390"]
    assert garnet.stop_phase == PHASE_BROKER
    assert garnet.ready is not None


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("redis://localhost", ("localhost", 6379, True)),
        ("redis://127.0.0.1:6390/0", ("127.0.0.1", 6390, True)),
        ("redis://:secret@10.0.0.5:6379", ("10.0.0.5", 6379, False)),
        ("rediss://localhost:6380", ("localhost", 6380, False)),
        ("unix:///var/run/redis.sock", ("localhost", 6379, False)),
    ],
)
def test_redis_endpoint(url: str, expected: tuple) -> None:
    assert stack.redis_endpoint(url) == expected


def test_broker_can_be_forced_external(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAPERLESS_WIN_BROKER", "external")
    assert stack.redis_endpoint("redis://127.0.0.1:6379")[2] is False


def test_redis_ping_talks_the_protocol() -> None:
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    received: list[bytes] = []

    def answer() -> None:
        conn, _ = server.accept()
        received.append(conn.recv(64))
        conn.sendall(b"+PONG\r\n")
        conn.close()

    thread = threading.Thread(target=answer)
    thread.start()
    assert stack.redis_ping("127.0.0.1", port)
    thread.join()
    server.close()
    assert received == [b"*1\r\n$4\r\nPING\r\n"]
    assert not stack.redis_ping("127.0.0.1", port, timeout=0.2)


def test_granian_environment_translation() -> None:
    assert stack.granian_env({}) == {
        "GRANIAN_HOST": "::",
        "GRANIAN_PORT": "8000",
        "GRANIAN_WORKERS": "1",
    }
    env = stack.granian_env(
        {
            "PAPERLESS_BIND_ADDR": "127.0.0.1",
            "PAPERLESS_PORT": "8100",
            "GRANIAN_WORKERS": "2",
            "PAPERLESS_FORCE_SCRIPT_NAME": "/paperless",
        },
    )
    assert env["GRANIAN_HOST"] == "127.0.0.1"
    assert env["GRANIAN_PORT"] == "8100"
    assert env["GRANIAN_WORKERS"] == "2"
    assert env["GRANIAN_URL_PATH_PREFIX"] == "/paperless"
    both = stack.granian_env({"GRANIAN_PORT": "9", "PAPERLESS_PORT": "8"})
    assert both["GRANIAN_PORT"] == "9"


def test_children_get_utf8_mode(tmp_path: Path) -> None:
    env = stack.child_environment(config(tmp_path))
    assert env["PYTHONUTF8"] == "1"
    assert env["PAPERLESS_WIN_RUN_DIR"] == str(tmp_path / "run")


def test_config_from_settings(tmp_path: Path) -> None:
    settings = SimpleNamespace(
        LOGGING_DIR=tmp_path / "log",
        TASK_WORKERS=3,
        CELERY_TASK_TIME_LIMIT=60,
    )
    cfg = stack.StackConfig.from_settings(
        settings,
        {
            "PAPERLESS_REDIS": "redis://h:1",
            "PAPERLESS_WIN_RECYCLE_AFTER": "5",
            "PAPERLESS_CONSUMER_DISABLE": "true",
        },
    )
    assert cfg.run_dir == tmp_path / "log" / "run"
    assert (cfg.task_workers, cfg.time_limit, cfg.recycle_after) == (3, 60, 5)
    assert cfg.consumer_disabled
    assert cfg.redis_url == "redis://h:1"


# -- worker side ----------------------------------------------------------------------------
def test_tracker_writes_and_clears_the_watchdog_record(tmp_path: Path) -> None:
    tracker = celery_signals.TaskTracker(
        tmp_path,
        2,
        recycle_after=3,
        wall=lambda: 123.0,
    )
    tracker.started("abc", "documents.tasks.consume_file")
    data = json.loads((tmp_path / "w2.json").read_text())
    assert data["task_id"] == "abc"
    assert data["task_name"] == "documents.tasks.consume_file"
    assert data["started_at"] == 123.0
    assert not tracker.finished_task()
    assert not (tmp_path / "w2.json").exists()


@pytest.mark.parametrize(
    ("recycle_after", "recycles_at"),
    [(1, 1), (3, 3), (0, None)],
)
def test_tracker_recycles_after_the_configured_number_of_tasks(
    tmp_path: Path,
    recycle_after: int,
    recycles_at: int | None,
) -> None:
    tracker = celery_signals.TaskTracker(tmp_path, 1, recycle_after=recycle_after)
    results = []
    for _ in range(5):
        tracker.started("t")
        results.append(tracker.finished_task())
    expected = [recycles_at is not None and n >= recycles_at for n in range(1, 6)]
    assert results == expected


def test_tracker_sees_the_stop_file(tmp_path: Path) -> None:
    tracker = celery_signals.TaskTracker(tmp_path, 1)
    assert not tracker.stop_requested()
    (tmp_path / "w1.stop").write_text("stop")
    assert tracker.stop_requested()


def test_signals_stay_off_outside_a_supervised_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(celery_signals.ENV_RUN_DIR, raising=False)
    monkeypatch.delenv(celery_signals.ENV_INDEX, raising=False)
    assert celery_signals.install() is None


# -- ctl helpers ----------------------------------------------------------------------------
def test_database_endpoint() -> None:
    assert ctl.database_endpoint({}) is None
    assert ctl.database_endpoint({"PAPERLESS_DBHOST": "db"}) == ("db", 5432)
    maria = {"PAPERLESS_DBHOST": "db", "PAPERLESS_DBENGINE": "mariadb"}
    assert ctl.database_endpoint(maria) == ("db", 3306)
    custom = {"PAPERLESS_DBHOST": "db", "PAPERLESS_DBPORT": "6000"}
    assert ctl.database_endpoint(custom) == ("db", 6000)


def test_wait_for_tcp_gives_up_after_the_timeout() -> None:
    clock = {"now": 0.0}

    def sleep(seconds: float) -> None:
        clock["now"] += seconds

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    reached = ctl.wait_for_tcp(
        "127.0.0.1",
        port,
        10,
        sleep=sleep,
        clock=lambda: clock["now"],
    )
    assert not reached
    assert 5 <= clock["now"] <= 10


def test_exclusive_lock_is_exclusive(tmp_path: Path) -> None:
    lock = tmp_path / "migration_lock"
    with ctl.exclusive_lock(lock):
        with pytest.raises(BlockingIOError), ctl.exclusive_lock(lock):
            pass
    with ctl.exclusive_lock(lock):  # free again afterwards
        pass


def test_static_files_are_recollected_when_the_version_changes(tmp_path: Path) -> None:
    assert ctl.static_needs_collecting(tmp_path, "3.5.1")
    (tmp_path / ".collected-version").write_text("3.5.1")
    assert not ctl.static_needs_collecting(tmp_path, "3.5.1")
    assert ctl.static_needs_collecting(tmp_path, "3.6.0")


def test_missing_ocr_languages() -> None:
    env = {"PAPERLESS_OCR_LANGUAGES": "deu fra eng"}
    assert ctl.missing_ocr_languages(env, {"eng", "deu"}) == ["fra"]
    assert ctl.missing_ocr_languages({}, set()) == []


def test_status_report() -> None:
    assert ctl.render_status(None, alive=False) == ["paperless-win is not running."]
    state = {
        "supervisor_pid": 42,
        "started_at": 0,
        "children": [
            {
                "name": "web",
                "state": "running",
                "pid": 7,
                "uptime_seconds": 3700,
                "restarts": 1,
                "last_exit": 1,
            },
            {
                "name": "beat",
                "state": "backoff",
                "pid": None,
                "uptime_seconds": 0,
                "restarts": 4,
                "last_exit": None,
            },
        ],
    }
    text = "\n".join(ctl.render_status(state, alive=True))
    assert "supervisor pid 42" in text
    assert "web" in text
    assert "1h 1m" in text
    assert "backoff" in text


@pytest.mark.parametrize(
    ("seconds", "text"),
    [(5, "5s"), (125, "2m 5s"), (3700, "1h 1m"), (90000, "1d 1h")],
)
def test_format_uptime(seconds: int, text: str) -> None:
    assert ctl.format_uptime(seconds) == text


def test_parser_knows_every_command() -> None:
    parser = ctl.build_parser()
    for command in ("init", "run", "check", "status", "stop"):
        assert parser.parse_args([command]).command == command
    args = parser.parse_args(["manage", "createsuperuser", "--noinput"])
    assert args.manage_args == ["createsuperuser", "--noinput"]
    assert parser.parse_args(["run", "--init"]).init is True


def test_every_command_can_print_its_help() -> None:
    """A stray ``%`` in a help text only fails when argparse renders it (Python 3.14 checks earlier)."""
    import argparse

    def walk(parser: argparse.ArgumentParser) -> None:
        parser.format_help()
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                for sub in action.choices.values():
                    walk(sub)

    walk(ctl.build_parser())


def test_pid_alive_knows_itself_and_a_dead_pid() -> None:
    import os

    assert jobs.pid_alive(os.getpid())
    assert not jobs.pid_alive(0)
    assert not jobs.pid_alive(2**22 + 12345)


def stop_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    exits: bool,
) -> list[list[int]]:
    """A running "supervisor" (pid 4242) that does, or does not, exit after a stop request."""
    cfg = config(tmp_path)
    monkeypatch.setattr(ctl, "load_settings", lambda: object())
    monkeypatch.setattr(
        stack.StackConfig,
        "from_settings",
        classmethod(lambda _c, _s: cfg),
    )
    monkeypatch.setattr(ctl, "running_supervisor", lambda _run_dir: 4242)
    monkeypatch.setattr(jobs, "pid_alive", lambda _pid: not exits)
    monkeypatch.setattr(jobs, "descendants", lambda _pid: [4243, 4244])
    monkeypatch.setattr(ctl.time, "sleep", lambda _s: None)
    clock = iter(range(0, 1000, 10))
    monkeypatch.setattr(ctl.time, "monotonic", lambda: float(next(clock)))
    killed: list[list[int]] = []
    monkeypatch.setattr(jobs, "kill_pids", killed.append)
    return killed


def test_stop_waits_for_the_supervisor_to_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    killed = stop_environment(tmp_path, monkeypatch, exits=True)
    args = SimpleNamespace(timeout=25.0, force=True)
    assert ctl.do_stop(args) == ctl.EXIT_OK
    assert killed == []  # it exited by itself: nothing to kill
    assert (tmp_path / "run" / "supervisor.stop").exists()


def test_stop_without_force_reports_a_supervisor_that_does_not_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    killed = stop_environment(tmp_path, monkeypatch, exits=False)
    assert ctl.do_stop(SimpleNamespace(timeout=25.0, force=False)) == ctl.EXIT_FAIL
    assert killed == []


def test_stop_force_kills_the_tree_of_a_supervisor_that_does_not_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    killed = stop_environment(tmp_path, monkeypatch, exits=False)
    assert ctl.do_stop(SimpleNamespace(timeout=25.0, force=True)) == ctl.EXIT_OK
    assert killed == [[4242, 4243, 4244]]
