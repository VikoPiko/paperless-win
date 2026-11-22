"""What the paperless stack consists of: the Windows equivalent of the s6 service definitions.

``docker/rootfs/etc/s6-overlay/s6-rc.d/svc-*`` is the spec. Start order here follows the
task file: broker, web server, scheduler, consumer, workers.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from paperless_win import jobs
from paperless_win import platform
from paperless_win.supervisor import PHASE_BROKER
from paperless_win.supervisor import PHASE_FRONT
from paperless_win.supervisor import PHASE_WORKER
from paperless_win.supervisor import ChildSpec

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Mapping

LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})
_TRUE = frozenset({"true", "1", "yes", "y", "t", "on"})

# Seconds the broker gets to answer PING, and how long we wait before starting flower
BROKER_READY_TIMEOUT = 30.0
FLOWER_DELAY = 5.0


def truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in _TRUE


def src_dir() -> Path:
    """Folder that holds ``manage.py``: ``<app>/src`` in both layouts."""
    return Path(__file__).resolve().parents[1]


def redis_endpoint(url: str) -> tuple[str, int, bool]:
    """``(host, port, managed)``. ``managed`` means we start Garnet for it ourselves."""
    parsed = urlparse(url)
    host = parsed.hostname or "localhost"
    port = parsed.port or 6379
    managed = (
        parsed.scheme in {"redis", ""}
        and host.lower() in LOOPBACK
        and os.environ.get("PAPERLESS_WIN_BROKER", "").lower() != "external"
    )
    return host, port, managed


def redis_ping(host: str, port: int, timeout: float = 1.0) -> bool:
    """True if something answers the Redis protocol. ``-NOAUTH`` still counts as alive."""
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall(b"*1\r\n$4\r\nPING\r\n")
            reply = sock.recv(64)
    except OSError:
        return False
    return reply.startswith((b"+PONG", b"-NOAUTH", b"-DENIED"))


def granian_env(environ: Mapping[str, str]) -> dict[str, str]:
    """The same translation ``svc-webserver/run`` does: GRANIAN_* wins, else PAPERLESS_*."""
    env = {
        "GRANIAN_HOST": environ.get("GRANIAN_HOST")
        or environ.get("PAPERLESS_BIND_ADDR")
        or "::",
        "GRANIAN_PORT": environ.get("GRANIAN_PORT")
        or environ.get("PAPERLESS_PORT")
        or "8000",
        "GRANIAN_WORKERS": environ.get("GRANIAN_WORKERS")
        or environ.get("PAPERLESS_WEBSERVER_WORKERS")
        or "1",
    }
    prefix = environ.get("PAPERLESS_FORCE_SCRIPT_NAME")
    if prefix:
        env["GRANIAN_URL_PATH_PREFIX"] = prefix
    return env


@dataclass(frozen=True)
class StackConfig:
    python: str
    src: Path
    run_dir: Path
    log_dir: Path
    redis_url: str
    task_workers: int
    time_limit: int
    recycle_after: int
    consumer_disabled: bool
    flower: bool
    garnet: str | None
    watchdog_grace: float = (
        30.0  # seconds past the task time limit before a worker is killed
    )
    stop_timeout: float = 10.0  # seconds a stopping worker gets to finish its task

    @classmethod
    def from_settings(cls, settings, environ: Mapping[str, str] | None = None):
        """Build from the loaded ``paperless.settings`` module and the environment."""
        environ = os.environ if environ is None else environ
        log_dir = Path(settings.LOGGING_DIR)
        run_dir = Path(environ.get("PAPERLESS_WIN_RUN_DIR") or log_dir / "run")
        return cls(
            python=sys.executable,
            src=src_dir(),
            run_dir=run_dir,
            log_dir=log_dir,
            redis_url=environ.get("PAPERLESS_REDIS") or "redis://localhost:6379",
            task_workers=max(int(getattr(settings, "TASK_WORKERS", 1)), 1),
            time_limit=int(getattr(settings, "CELERY_TASK_TIME_LIMIT", 1800)),
            recycle_after=int(environ.get("PAPERLESS_WIN_RECYCLE_AFTER") or 1),
            consumer_disabled=truthy(environ.get("PAPERLESS_CONSUMER_DISABLE")),
            flower=truthy(environ.get("PAPERLESS_ENABLE_FLOWER")),
            garnet=platform.find_binary("GarnetServer"),
            watchdog_grace=float(environ.get("PAPERLESS_WIN_WATCHDOG_GRACE") or 30),
            stop_timeout=float(environ.get("PAPERLESS_WIN_STOP_TIMEOUT") or 10),
        )


def build_specs(
    cfg: StackConfig,
    environ: Mapping[str, str] | None = None,
) -> list[ChildSpec]:
    environ = os.environ if environ is None else environ
    specs: list[ChildSpec] = []
    host, port, managed = redis_endpoint(cfg.redis_url)
    celery = [cfg.python, "-m", "celery", "--skip-checks", "--app", "paperless"]

    if managed:
        if not cfg.garnet:
            msg = (
                "Garnet (the Redis-compatible broker) was not found. Reinstall paperless-win, "
                "set PAPERLESS_BIN_GARNETSERVER, or point PAPERLESS_REDIS at a Redis server "
                "on another host."
            )
            raise FileNotFoundError(msg)
        specs.append(
            ChildSpec(
                name="garnet",
                argv=[
                    cfg.garnet,
                    "--bind",
                    host if host != "localhost" else "127.0.0.1",
                    "--port",
                    str(port),
                ],
                cwd=cfg.run_dir,
                ready=lambda: redis_ping(host, port),
                ready_timeout=BROKER_READY_TIMEOUT,
                stop_phase=PHASE_BROKER,
            ),
        )

    specs.append(
        ChildSpec(
            name="web",
            argv=[
                cfg.python,
                "-m",
                "granian",
                "--interface",
                "asginl",
                "--ws",
                "--loop",
                "asyncio",
                "paperless.asgi:application",
            ],
            cwd=cfg.src,
            env=granian_env(environ),
            stop_phase=PHASE_FRONT,
        ),
    )
    specs.append(
        ChildSpec(
            name="beat",
            argv=[*celery, "beat", "--loglevel", "INFO"],
            cwd=cfg.src,
            stop_phase=PHASE_FRONT,
        ),
    )
    if not cfg.consumer_disabled:
        specs.append(
            ChildSpec(
                name="consumer",
                argv=[cfg.python, "manage.py", "document_consumer", "--skip-checks"],
                cwd=cfg.src,
                stop_phase=PHASE_FRONT,
            ),
        )
    for index in range(1, cfg.task_workers + 1):
        specs.append(
            ChildSpec(
                name=f"worker{index}",
                argv=[
                    *celery,
                    "worker",
                    "-P",
                    "solo",
                    "-n",
                    f"w{index}@%h",
                    "--loglevel",
                    "INFO",
                    "--without-mingle",
                    "--without-gossip",
                    "--prefetch-multiplier",
                    "1",
                ],
                cwd=cfg.src,
                env={
                    "PAPERLESS_WIN_WORKER_INDEX": str(index),
                    "PAPERLESS_WIN_RECYCLE_AFTER": str(cfg.recycle_after),
                },
                restart_on_clean_exit=True,
                worker_index=index,
                stop_phase=PHASE_WORKER,
            ),
        )
    if cfg.flower:
        flower_conf = cfg.src / "paperless" / "flowerconfig.py"
        conf_args = [f"--conf={flower_conf}"] if flower_conf.is_file() else []
        specs.append(
            ChildSpec(
                name="flower",
                argv=[*celery, "flower", *conf_args],
                cwd=cfg.src,
                start_delay=FLOWER_DELAY,
                stop_phase=PHASE_FRONT,
            ),
        )
    return specs


def child_environment(cfg: StackConfig) -> dict[str, str]:
    """Environment every child starts with (on top of whatever was loaded from paperless.conf)."""
    env = dict(os.environ)
    env.setdefault("DJANGO_SETTINGS_MODULE", "paperless.settings")
    env["PYTHONUTF8"] = (
        "1"  # Windows' default code page would break non-ASCII file names
    )
    env["PYTHONUNBUFFERED"] = "1"
    env["PAPERLESS_WIN_RUN_DIR"] = str(cfg.run_dir)
    return env


def make_fail_task(
    cfg: StackConfig,
    env: Mapping[str, str],
    log: Callable[[str], None],
) -> Callable[[str, str], None]:
    """Marks a task as failed in the database (``winport_fail_task``), in the background."""

    def run(task_id: str, reason: str) -> None:
        def work() -> None:
            try:
                result = subprocess.run(
                    [
                        cfg.python,
                        "manage.py",
                        "winport_fail_task",
                        task_id,
                        "--reason",
                        reason,
                    ],
                    cwd=cfg.src,
                    env=dict(env),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=180,
                    check=False,
                    **(
                        {"creationflags": jobs.CREATE_NO_WINDOW}
                        if platform.IS_WINDOWS
                        else {}
                    ),
                )
                if result.returncode != 0:
                    log(
                        f"could not mark task {task_id} as failed: {result.stderr.strip()[-300:]}",
                    )
            except (OSError, subprocess.SubprocessError) as exc:
                log(f"could not mark task {task_id} as failed: {exc}")

        threading.Thread(target=work, name="fail-task", daemon=True).start()

    return run
