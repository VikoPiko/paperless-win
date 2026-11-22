"""``paperless-ctl``: init, run, check, manage, status and stop for paperless-win.

Run it as ``python -m paperless_win <command>`` (the installer ships a ``paperless-ctl.exe``
launcher for the same entry point).

* ``init``    the s6 ``init-*`` scripts: folders, migrations, superuser, indexes, static files
* ``run``     start and supervise the whole stack in the foreground (what the service runs)
* ``check``   Django checks plus tools, broker and folder permissions, as a readable report
* ``manage``  ``manage.py`` with the right environment
* ``status``  which children are up, their PIDs, uptime and restart counts
* ``stop``    ask a running supervisor to shut down
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import os
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from paperless_win import jobs
from paperless_win import platform
from paperless_win import service
from paperless_win import setup_conf
from paperless_win import stack
from paperless_win.supervisor import STATE_FILE
from paperless_win.supervisor import STOP_REQUEST_FILE
from paperless_win.supervisor import ChildLogs
from paperless_win.supervisor import ManagedProcess
from paperless_win.supervisor import Supervisor
from paperless_win.supervisor import Watchdog

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Sequence

EXIT_OK, EXIT_FAIL, EXIT_USAGE = 0, 1, 2
DB_WAIT_SECONDS = 60
STOP_WAIT_SECONDS = 40


# -- settings -------------------------------------------------------------------------------
class ConfigError(Exception):
    """paperless.conf or the environment could not be turned into settings."""


def load_settings():
    """Import ``paperless.settings``: reads paperless.conf and applies the Windows bootstrap."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "paperless.settings")
    src = str(stack.src_dir())
    if src not in sys.path:
        sys.path.insert(0, src)
    import importlib

    try:
        return importlib.import_module("paperless.settings")
    except Exception as exc:
        raise ConfigError(f"{type(exc).__name__}: {exc}") from exc


def say(text: str = "") -> None:
    print(text, flush=True)  # noqa: T201


# -- manage.py ------------------------------------------------------------------------------
def run_manage(cfg: stack.StackConfig, env: dict[str, str], *args: str) -> int:
    return subprocess.call(
        [cfg.python, "manage.py", *args],
        cwd=cfg.src,
        env=env,
    )


# -- init -----------------------------------------------------------------------------------
@contextlib.contextmanager
def exclusive_lock(path: Path):
    """Non-blocking exclusive lock on ``path`` (s6-setlock -n). Raises ``BlockingIOError``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    try:
        if platform.IS_WINDOWS:
            import msvcrt

            try:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)  # type: ignore[attr-defined]
            except OSError as exc:
                raise BlockingIOError(str(path)) from exc
        else:
            import fcntl

            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise BlockingIOError(str(path)) from exc
        yield
    finally:
        handle.close()  # closing releases the lock on both platforms


def wait_for_tcp(
    host: str,
    port: int,
    timeout: float,
    *,
    sleep=time.sleep,
    clock=time.monotonic,
) -> bool:
    """The s6 ``init-wait-for-db`` loop: retry with a growing delay until ``timeout``."""
    deadline = clock() + timeout
    delay = 1.0
    while True:
        try:
            with socket.create_connection((host, port), timeout=3):
                return True
        except OSError:
            if clock() + delay > deadline:
                return False
            sleep(delay)
            delay = min(delay + 1, 5)


def database_endpoint(environ=os.environ) -> tuple[str, int] | None:
    """Host and port of an external database, or ``None`` for SQLite."""
    host = environ.get("PAPERLESS_DBHOST")
    if not host:
        return None
    engine = environ.get("PAPERLESS_DBENGINE", "postgresql").lower()
    default_port = 3306 if engine == "mariadb" else 5432
    return host, int(environ.get("PAPERLESS_DBPORT") or default_port)


def tesseract_languages(tesseract: str | None) -> set[str]:
    if not tesseract:
        return set()
    try:
        out = subprocess.run(
            [tesseract, "--list-langs"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return set()
    return {
        line.strip()
        for line in (out.stdout + out.stderr).splitlines()[1:]
        if line.strip() and " " not in line.strip()
    }


def missing_ocr_languages(environ, installed: set[str]) -> list[str]:
    wanted = (environ.get("PAPERLESS_OCR_LANGUAGES") or "").split()
    return [lang for lang in wanted if lang not in installed]


def compile_bytecode(cfg: stack.StackConfig) -> None:
    """Same scope as ``init-compile-bytecode``: only what every start imports."""
    import sysconfig

    site = Path(sysconfig.get_paths()["purelib"])
    names = (
        "django",
        "celery",
        "kombu",
        "rest_framework",
        "django_filters",
        "whitenoise",
        "corsheaders",
        "django_extensions",
        "guardian",
        "allauth",
        "drf_spectacular",
        "drf_spectacular_sidecar",
        "compression_middleware",
    )
    targets = [str(cfg.src), *(str(site / n) for n in names if (site / n).is_dir())]
    env = {k: v for k, v in os.environ.items() if k != "PYTHONDONTWRITEBYTECODE"}
    code = subprocess.call(
        [cfg.python, "-m", "compileall", "-q", *targets],
        env=env,
    )
    if code != 0:
        say(
            "  warning: compileall reported errors (read-only install?); continuing without a bytecode cache",
        )


def static_needs_collecting(static_root: Path, version: str) -> bool:
    marker = static_root / ".collected-version"
    try:
        return marker.read_text(encoding="utf-8").strip() != version
    except OSError:
        return True


def do_init(cfg: stack.StackConfig, settings, env: dict[str, str]) -> int:
    from paperless.version import __full_version_str__ as version

    steps: list[tuple[str, Callable[[], bool]]] = []

    def folders() -> bool:
        data = Path(settings.DATA_DIR)
        for directory in (
            data,
            data / "index",
            Path(settings.MEDIA_ROOT),
            Path(settings.ORIGINALS_DIR),
            Path(settings.THUMBNAIL_DIR),
            Path(settings.CONSUMPTION_DIR),
            Path(settings.SCRATCH_DIR),
            cfg.log_dir,
            cfg.run_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        return True

    def wait_for_db() -> bool:
        endpoint = database_endpoint()
        if endpoint is None:
            say("  SQLite, nothing to wait for")
            return True
        host, port = endpoint
        say(f"  waiting for the database at {host}:{port} (up to {DB_WAIT_SECONDS} s)")
        return wait_for_tcp(host, port, DB_WAIT_SECONDS)

    def migrations() -> bool:
        if run_manage(cfg, env, "check", "--tag", "compatibility", "paperless") != 0:
            return False
        try:
            with exclusive_lock(Path(settings.DATA_DIR) / "migration_lock"):
                return (
                    run_manage(cfg, env, "migrate", "--skip-checks", "--no-input") == 0
                )
        except BlockingIOError:
            say("  another process is migrating the database right now")
            return False

    def superuser() -> bool:
        if not env.get("PAPERLESS_ADMIN_USER"):
            say("  PAPERLESS_ADMIN_USER is not set, not creating a superuser")
            return True
        return run_manage(cfg, env, "manage_superuser") == 0

    def tesseract_langs() -> bool:
        missing = missing_ocr_languages(
            os.environ,
            tesseract_languages(platform.find_binary("tesseract")),
        )
        if missing:
            say(
                f"  language data missing for: {', '.join(missing)}. paperless-win cannot download "
                "them for you; copy the .traineddata files into the tessdata folder.",
            )
        return True  # a warning only, like a skipped apt package on Linux

    def system_checks() -> bool:
        return run_manage(cfg, env, "check") == 0

    def search_index() -> bool:
        return (
            run_manage(
                cfg,
                env,
                "document_index",
                "reindex",
                "--if-needed",
                "--no-progress-bar",
            )
            == 0
        )

    def llm_index() -> bool:
        return run_manage(cfg, env, "document_llmindex", "migrate") == 0

    def static_files() -> bool:
        static_root = Path(settings.STATIC_ROOT)
        if not static_needs_collecting(static_root, version):
            say(f"  already collected for {version}")
            return True
        if (
            run_manage(cfg, env, "collectstatic", "--no-input", "--clear", "-v", "0")
            != 0
        ):
            return False
        (static_root / ".collected-version").write_text(version, encoding="utf-8")
        return True

    def bytecode() -> bool:
        compile_bytecode(cfg)
        return True

    steps = [
        ("folders", folders),
        ("wait for the database", wait_for_db),
        ("migrations", migrations),
        ("superuser", superuser),
        ("tesseract languages", tesseract_langs),
        ("system checks", system_checks),
        ("search index", search_index),
        ("LLM index", llm_index),
        ("static files", static_files),
        ("bytecode", bytecode),
    ]
    started = time.monotonic()
    for name, step in steps:
        say(f"[init] {name}")
        if not step():
            say(f"[init] FAILED: {name}")
            return EXIT_FAIL
    say(f"[init] done in {time.monotonic() - started:.0f} s")
    return EXIT_OK


# -- run ------------------------------------------------------------------------------------
def build_supervisor(cfg: stack.StackConfig, settings) -> tuple[Supervisor, ChildLogs]:
    logs = ChildLogs(cfg.log_dir)
    env = stack.child_environment(cfg)
    console = logging.getLogger("paperless.winport.supervisor")
    if not console.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(asctime)s [supervisor] %(message)s"))
        console.addHandler(handler)
        console.setLevel(logging.INFO)
        console.propagate = False

    def event(text: str) -> None:
        console.info(text)
        logs.event(text)

    specs = stack.build_specs(cfg)

    def spawn(spec):
        return ManagedProcess(spec, {**env, **spec.env}, logs)

    supervisor = Supervisor(
        specs,
        spawn,
        run_dir=cfg.run_dir,
        watchdog=Watchdog(cfg.run_dir, cfg.time_limit, cfg.watchdog_grace),
        fail_task=stack.make_fail_task(cfg, env, event),
        events=event,
    )
    return supervisor, logs


def running_supervisor(run_dir: Path) -> int | None:
    state = read_state(run_dir)
    if state:
        pid = int(state.get("supervisor_pid") or 0)
        if pid and pid != os.getpid() and jobs.pid_alive(pid):
            return pid
    return None


def enable_ctrl_c() -> None:
    """Undo an inherited "ignore Ctrl-C" flag (Windows).

    A process started by something that disabled Ctrl-C (a script launched in the background,
    CREATE_NEW_PROCESS_GROUP) inherits that setting and would never see Ctrl-C. The supervisor
    must always be stoppable from its console.
    """
    if platform.IS_WINDOWS:
        import ctypes

        ctypes.WinDLL("kernel32").SetConsoleCtrlHandler(None, False)  # noqa: FBT003


def do_run(args: argparse.Namespace) -> int:
    settings = load_settings()
    cfg = stack.StackConfig.from_settings(settings)
    other = running_supervisor(cfg.run_dir)
    if other:
        say(
            f"paperless-win is already running (supervisor pid {other}). Use 'paperless-ctl stop' first.",
        )
        return EXIT_FAIL
    env = stack.child_environment(cfg)
    if args.init:
        code = do_init(cfg, settings, env)
        if code != EXIT_OK:
            return code
    try:
        supervisor, logs = build_supervisor(cfg, settings)
    except FileNotFoundError as exc:
        say(f"error: {exc}")
        return EXIT_FAIL

    stopping = {"flag": False}

    def request_stop(signum, frame) -> None:
        stopping["flag"] = True

    enable_ctrl_c()
    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        sig = getattr(signal, name, None)
        if sig is not None:
            with contextlib.suppress(ValueError, OSError):
                signal.signal(sig, request_stop)
    host = env.get("GRANIAN_HOST") or stack.granian_env(os.environ)["GRANIAN_HOST"]
    port = stack.granian_env(os.environ)["GRANIAN_PORT"]
    supervisor.log(
        f"paperless-win starting (web on port {port}, {cfg.task_workers} worker(s), bind {host})",
    )
    try:
        return supervisor.run(lambda: stopping["flag"], cfg.stop_timeout)
    finally:
        logs.close()


# -- check ----------------------------------------------------------------------------------
@dataclass
class Finding:
    level: str  # ok | warn | fail
    text: str


def writable(directory: Path) -> bool:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / f".write-test-{os.getpid()}"
        probe.write_text("x")
        probe.unlink()
    except OSError:
        return False
    return True


def collect_findings(cfg: stack.StackConfig, settings) -> list[Finding]:
    found: list[Finding] = []

    def add(level: str, text: str) -> None:
        found.append(Finding(level, text))

    for name, required in (
        ("tesseract", True),
        ("gs", True),
        ("pdftoppm", True),
        ("unpaper", False),
        ("pngquant", False),
    ):
        path = platform.find_binary(name)
        if path:
            add("ok", f"{name}: {path}")
        else:
            add(
                "fail" if required else "warn",
                f"{name}: not found" + ("" if required else " (optional)"),
            )
    try:
        import magic  # noqa: F401

        add("ok", "libmagic: loads")
    except Exception as exc:
        add("fail", f"libmagic: {exc}")

    host, port, managed = stack.redis_endpoint(cfg.redis_url)
    if stack.redis_ping(host, port):
        add("ok", f"broker: answering on {host}:{port}")
    elif managed:
        if cfg.garnet:
            add(
                "ok",
                f"broker: not running yet; 'run' will start Garnet ({cfg.garnet})",
            )
        else:
            add(
                "fail",
                f"broker: Garnet not found and nothing is listening on {host}:{port}",
            )
    else:
        add("fail", f"broker: nothing answers at {host}:{port}")

    for label, directory in (
        ("data", settings.DATA_DIR),
        ("media", settings.MEDIA_ROOT),
        ("consume", settings.CONSUMPTION_DIR),
        ("scratch", settings.SCRATCH_DIR),
        ("logs", cfg.log_dir),
    ):
        ok = writable(Path(directory))
        add(
            "ok" if ok else "fail",
            f"{label} folder {'writable' if ok else 'NOT writable'}: {directory}",
        )
    return found


def do_check(args: argparse.Namespace) -> int:
    settings = load_settings()
    cfg = stack.StackConfig.from_settings(settings)
    findings = collect_findings(cfg, settings)
    labels = {"ok": " OK ", "warn": "WARN", "fail": "FAIL"}
    for item in findings:
        say(f"[{labels[item.level]}] {item.text}")
    say("")
    say("Django system checks:")
    django_code = run_manage(cfg, stack.child_environment(cfg), "check")
    failed = django_code != 0 or any(f.level == "fail" for f in findings)
    say("")
    say("check FAILED" if failed else "check passed")
    return EXIT_FAIL if failed else EXIT_OK


# -- status / stop --------------------------------------------------------------------------
def read_state(run_dir: Path) -> dict | None:
    try:
        return json.loads((run_dir / STATE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def format_uptime(seconds: float) -> str:
    seconds = int(seconds)
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, secs = divmod(rest, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def render_status(state: dict | None, *, alive: bool) -> list[str]:
    if not state or not alive:
        return ["paperless-win is not running."]
    now = time.time()
    uptime = format_uptime(now - state.get("started_at", now))
    lines = [
        f"paperless-win is running (supervisor pid {state['supervisor_pid']}, up {uptime})",
        "",
        f"{'child':<10} {'state':<9} {'pid':>7} {'uptime':>9} {'restarts':>9}  last exit",
    ]
    for child in state.get("children", []):
        uptime = (
            format_uptime(child.get("uptime_seconds", 0)) if child.get("pid") else "-"
        )
        last = "" if child.get("last_exit") is None else str(child["last_exit"])
        lines.append(
            f"{child['name']:<10} {child['state']:<9} {child.get('pid') or '-':>7} {uptime:>9} "
            f"{child.get('restarts', 0):>9}  {last}",
        )
    return lines


def do_status(args: argparse.Namespace) -> int:
    cfg = stack.StackConfig.from_settings(load_settings())
    state = read_state(cfg.run_dir)
    alive = bool(state) and jobs.pid_alive(int(state.get("supervisor_pid") or 0))
    for line in render_status(state, alive=alive):
        say(line)
    return EXIT_OK if alive else EXIT_FAIL


def do_stop(args: argparse.Namespace) -> int:
    cfg = stack.StackConfig.from_settings(load_settings())
    pid = running_supervisor(cfg.run_dir)
    if not pid:
        say("paperless-win is not running.")
        return EXIT_OK
    cfg.run_dir.mkdir(parents=True, exist_ok=True)
    (cfg.run_dir / STOP_REQUEST_FILE).write_text("stop")
    say(f"asked supervisor {pid} to stop")
    timeout = getattr(args, "timeout", STOP_WAIT_SECONDS)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not jobs.pid_alive(pid):
            say("stopped")
            return EXIT_OK
        time.sleep(0.5)
    say(f"supervisor {pid} did not exit within {timeout:g} s")
    if getattr(args, "force", False):
        # the Windows service must not stay "stopping" for ever: end the whole tree
        victims = [pid, *jobs.descendants(pid)]
        jobs.kill_pids(victims)
        say(f"killed the supervisor and {len(victims) - 1} other process(es)")
        return EXIT_OK
    return EXIT_FAIL


def do_init_command(args: argparse.Namespace) -> int:
    settings = load_settings()
    cfg = stack.StackConfig.from_settings(settings)
    env = stack.child_environment(cfg)
    if args.admin_user:
        env["PAPERLESS_ADMIN_USER"] = args.admin_user
        if args.admin_password_file:
            # read (and delete) the file the installer wrote; it never reaches a command line
            env["PAPERLESS_ADMIN_PASSWORD"] = setup_conf.read_admin_password(
                Path(args.admin_password_file),
            )
    return do_init(cfg, settings, env)


def do_setup(args: argparse.Namespace) -> int:
    """Write paperless.conf (used by the installer). Needs no settings, so it works before init."""
    data_dir = Path(args.data_dir)
    conf = Path(args.conf) if args.conf else None
    if conf is None:
        root = platform.program_data_dir() or data_dir
        conf = root / "paperless.conf"
    values = setup_conf.ConfValues(
        data_dir=data_dir,
        consume_dir=Path(args.consume_dir) if args.consume_dir else None,
        media_dir=Path(args.media_dir) if args.media_dir else None,
        ocr_languages=args.ocr_languages,
        port=args.port,
        bind=args.bind,
        redis_port=args.redis_port,
    )
    outcome = setup_conf.write_conf(conf, values, force=args.force)
    say(f"{conf}: {outcome}")
    return EXIT_OK


def do_manage(args: argparse.Namespace) -> int:
    settings = load_settings()
    cfg = stack.StackConfig.from_settings(settings)
    return run_manage(cfg, stack.child_environment(cfg), *args.manage_args)


# -- entry point ----------------------------------------------------------------------------
# -- service ---------------------------------------------------------------------------------
def service_context() -> tuple[service.Layout, dict[str, Path], int]:
    """Layout, configured data folders and web port; falls back to defaults if the
    configuration cannot be loaded (so the service can still be installed and repaired)."""
    try:
        settings = load_settings()
    except Exception as exc:
        say(
            f"warning: configuration could not be loaded ({exc}); using the default folders",
        )
        layout = service.default_layout()
        root = layout.data_root
        dirs = {
            "data": root / "data",
            "media": root / "media",
            "consume": root / "consume",
            "scratch": root / "scratch",
            "logs": layout.log_dir,
        }
        return layout, dirs, 8000
    layout = service.default_layout(Path(settings.LOGGING_DIR))
    dirs = {
        "data": Path(settings.DATA_DIR),
        "media": Path(settings.MEDIA_ROOT),
        "consume": Path(settings.CONSUMPTION_DIR),
        "scratch": Path(settings.SCRATCH_DIR),
        "logs": Path(settings.LOGGING_DIR),
    }
    return layout, dirs, int(stack.granian_env(os.environ)["GRANIAN_PORT"])


def _account_from(args: argparse.Namespace) -> service.Account:
    password = None
    text = getattr(args, "account", "virtual") or "virtual"
    account = service.Account.parse(text)
    if account.kind == "user":
        password = os.environ.get("PAPERLESS_WIN_SERVICE_PASSWORD")
        if password is None:
            import getpass

            password = getpass.getpass(f"Password for {account.display}: ")
        account = service.Account.parse(text, password)
    return account


def do_service(args: argparse.Namespace) -> int:
    action = args.service_command
    if action == "xml":
        layout, _, _ = service_context()
        say(service.render_xml(layout, service.Account.parse(args.account)))
        return EXIT_OK
    if action == "status":
        state = service.service_state() if platform.IS_WINDOWS else None
        if state is None:
            say("The paperless-win service is not installed.")
            return 3
        say(f"The paperless-win service is {state}.")
        return EXIT_OK if state == "RUNNING" else EXIT_FAIL
    layout, dirs, port = service_context()
    if action == "install":
        account = _account_from(args)
        service.install(
            layout,
            account,
            dirs,
            force=args.force,
            winsw_source=Path(args.winsw) if args.winsw else None,
        )
        say(f"Service installed (account {account.display}).")
        if args.firewall:
            service.firewall(port)
            say(
                f"Windows Firewall: TCP port {port} allowed on private and domain networks.",
            )
        if args.start:
            service.winsw(layout, "start")
            say("Service started.")
        return EXIT_OK
    if action == "uninstall":
        service.uninstall(layout)
        service.firewall(port, remove=True)
        say("Service removed. Data, logs and configuration were not touched.")
        return EXIT_OK
    if action in {"start", "stop", "restart"}:
        if not service.is_admin():
            raise service.ServiceError(service.ERROR_NOT_ADMIN)
        # WinSW's own `stop`/`restart` return before the service has changed state: wait for it here
        if action == "stop":
            service.stop(layout)
        elif action == "restart":
            service.restart(layout)
        else:
            service.winsw(layout, "start")
        say(f"Service {action}: done.")
        return EXIT_OK
    if action == "set-account":
        account = _account_from(args)
        service.set_account(layout, account, dirs)
        say(f"Service now runs as {account.display}.")
        return EXIT_OK
    if action == "acl":
        if not service.is_admin():
            raise service.ServiceError(service.ERROR_NOT_ADMIN)
        service.apply_acls(layout, service.Account.parse(args.account), dirs)
        say("Folder permissions applied.")
        return EXIT_OK
    if action == "firewall":
        service.firewall(args.port or port, remove=args.firewall_command == "remove")
        say("Firewall rule updated.")
        return EXIT_OK
    return EXIT_USAGE


def add_service_commands(sub) -> None:
    svc = sub.add_parser("service", help="install and control the Windows service")
    svc_sub = svc.add_subparsers(dest="service_command", required=True)
    account_help = "virtual (default), system, or DOMAIN\\user"

    install = svc_sub.add_parser("install", help="register the service (administrator)")
    install.add_argument("--account", default="virtual", help=account_help)
    install.add_argument("--start", action="store_true", help="start it afterwards")
    install.add_argument(
        "--force",
        action="store_true",
        help="replace an installed service",
    )
    install.add_argument(
        "--firewall",
        action="store_true",
        help="allow the web port in the Windows Firewall",
    )
    install.add_argument("--winsw", help="path of the WinSW executable to copy")
    svc_sub.add_parser("uninstall", help="remove the service (data is kept)")
    for name in ("start", "stop", "restart", "status"):
        svc_sub.add_parser(name, help=f"{name} the service")
    set_account = svc_sub.add_parser(
        "set-account",
        help="run the service as another user (needed for a NAS or domain share)",
    )
    set_account.add_argument(
        "account",
        help="DOMAIN\\user or .\\user; the password is asked for",
    )
    acl = svc_sub.add_parser("acl", help="(re)apply the folder permissions")
    acl.add_argument("--account", default="virtual", help=account_help)
    fw = svc_sub.add_parser(
        "firewall",
        help="allow or close the web port in the Windows Firewall",
    )
    fw.add_argument("firewall_command", choices=("allow", "remove"))
    fw.add_argument("--port", type=int)
    xml = svc_sub.add_parser("xml", help="print the WinSW configuration")
    xml.add_argument("--account", default="virtual", help=account_help)
    svc.set_defaults(func=do_service)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="paperless-ctl",
        description="Control paperless-win (unofficial Windows port of paperless-ngx).",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    init_parser = sub.add_parser(
        "init",
        help="create folders, migrate the database, build indexes",
    )
    init_parser.set_defaults(func=do_init_command)
    init_parser.add_argument(
        "--admin-user",
        help="create this superuser if none exists",
    )
    init_parser.add_argument(
        "--admin-password-file",
        help="file holding the password of --admin-user; it is deleted after reading",
    )
    setup = sub.add_parser("setup", help="write paperless.conf for a new installation")
    setup.add_argument("--data-dir", required=True)
    setup.add_argument("--consume-dir")
    setup.add_argument("--media-dir")
    setup.add_argument(
        "--conf",
        help="where to write it (default: %%ProgramData%%\\paperless-win)",
    )
    setup.add_argument("--ocr-languages", default="eng", help="for example eng+deu")
    setup.add_argument("--port", type=int, default=8000)
    setup.add_argument(
        "--bind",
        default="127.0.0.1",
        help="0.0.0.0 to allow other computers",
    )
    setup.add_argument("--redis-port", type=int, default=6379)
    setup.add_argument(
        "--force",
        action="store_true",
        help="rewrite it, keeping the secret key",
    )
    setup.set_defaults(func=do_setup)
    run = sub.add_parser("run", help="start and supervise all services (foreground)")
    run.add_argument("--init", action="store_true", help="run 'init' first")
    run.set_defaults(func=do_run)
    sub.add_parser(
        "check",
        help="verify tools, broker, folders and Django checks",
    ).set_defaults(func=do_check)
    sub.add_parser("status", help="show the supervised processes").set_defaults(
        func=do_status,
    )
    stop = sub.add_parser("stop", help="ask a running supervisor to shut down")
    stop.add_argument(
        "--timeout",
        type=float,
        default=STOP_WAIT_SECONDS,
        help="seconds to wait for the supervisor to exit",
    )
    stop.add_argument(
        "--force",
        action="store_true",
        help="kill the supervisor and everything it started if it does not exit in time",
    )
    stop.set_defaults(func=do_stop)
    add_service_commands(sub)
    manage = sub.add_parser("manage", help="run manage.py with the right environment")
    manage.add_argument("manage_args", nargs=argparse.REMAINDER)
    manage.set_defaults(func=do_manage)
    return parser


EXIT_ERROR = 4


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except service.ServiceError as exc:
        say(f"error: {exc}")
        return EXIT_ERROR
    except ConfigError as exc:
        say(f"error: the configuration is invalid: {exc}")
        say(
            "Check paperless.conf (and the PAPERLESS_* variables) and run 'paperless-ctl check'.",
        )
        return EXIT_ERROR
