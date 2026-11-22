"""Windows service glue: the WinSW configuration, folder permissions, firewall rule.

paperless-win runs as one Windows service. WinSW (a small, MIT-licensed service wrapper)
registers ``paperless-ctl run`` with the Service Control Manager, restarts it when it fails and
stops it by running ``paperless-ctl stop`` (which makes the supervisor shut everything down in
order). There is no pywin32 service code (D6).

Everything here that builds a command or a document is a pure function, so it is unit-tested on
any OS. The functions that change the machine (``install``, ``apply_acls`` ...) need an elevated
prompt and are exercised by ``windows/scripts/test-service.ps1``.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import struct
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from xml.etree import ElementTree as ET

from paperless_win import platform

if TYPE_CHECKING:
    from collections.abc import Iterable
    from collections.abc import Mapping

SERVICE_ID = "paperless-win"
DESCRIPTION = (
    "paperless-win: unofficial Windows port of paperless-ngx (document archive with OCR). "
    "Runs the web server, consumer and workers."
)
EXE_NAME = "paperless-win-service.exe"
WINSW_DEV_NAME = "WinSW-x64.exe"
FIREWALL_RULE = "paperless-win web interface"

STOP_TIMEOUT_SECONDS = 30
STOP_COMMAND_TIMEOUT_SECONDS = (
    25  # the stop command gives up a little before WinSW kills the tree
)

# Well-known SIDs, so ACLs do not depend on the language of the Windows installation.
SID_SYSTEM = "S-1-5-18"
SID_ADMINISTRATORS = "S-1-5-32-544"
SID_USERS = "S-1-5-32-545"

ERROR_NOT_ADMIN = (
    "This command changes the Windows service and must run in an elevated prompt "
    "(right-click PowerShell, 'Run as administrator')."
)


# -- accounts -------------------------------------------------------------------------------
def virtual_account_sid(name: str = SERVICE_ID) -> str:
    """SID of ``NT SERVICE\\<name>``: SHA-1 of the upper-cased name, as five little-endian DWORDs.

    Windows derives it from the name alone, so it can be used in an ACL before the service
    exists (``icacls`` cannot resolve the name until then). Matches ``sc showsid``.
    """
    digest = hashlib.sha1(name.upper().encode("utf-16-le")).digest()
    return "S-1-5-80-" + "-".join(str(part) for part in struct.unpack("<5I", digest))


@dataclass(frozen=True)
class Account:
    """Who the service runs as."""

    kind: str  # "virtual" | "system" | "user"
    domain: str = ""
    user: str = ""
    password: str | None = None

    @classmethod
    def virtual(cls) -> Account:
        return cls("virtual", "NT SERVICE", SERVICE_ID)

    @classmethod
    def system(cls) -> Account:
        return cls("system", "NT AUTHORITY", "SYSTEM")

    @classmethod
    def parse(cls, text: str, password: str | None = None) -> Account:
        """``virtual``, ``system``, ``DOMAIN\\user``, ``.\\user`` or ``user@domain``."""
        lowered = text.strip().lower()
        if lowered in {"virtual", "nt service\\" + SERVICE_ID}:
            return cls.virtual()
        if lowered in {"system", "localsystem"}:
            return cls.system()
        if "\\" in text:
            domain, user = text.split("\\", 1)
        elif "@" in text:
            user, domain = text.split("@", 1)
        else:
            domain, user = ".", text
        if not user:
            msg = f"not a valid account name: {text!r}"
            raise ValueError(msg)
        return cls("user", domain or ".", user, password)

    @property
    def principal(self) -> str:
        """Name for ``icacls``: a SID where one is known, else ``DOMAIN\\user``."""
        if self.kind == "virtual":
            return "*" + virtual_account_sid()
        if self.kind == "system":
            return "*" + SID_SYSTEM
        return f"{self.domain}\\{self.user}"

    @property
    def display(self) -> str:
        return f"{self.domain}\\{self.user}"


# -- layout ---------------------------------------------------------------------------------
@dataclass(frozen=True)
class Layout:
    app_dir: Path
    python: Path
    src_dir: Path
    service_dir: Path
    data_root: Path
    conf_path: Path
    log_dir: Path

    @property
    def exe(self) -> Path:
        return self.service_dir / EXE_NAME

    @property
    def xml(self) -> Path:
        return self.service_dir / (EXE_NAME.removesuffix(".exe") + ".xml")


def default_layout(log_dir: Path | None = None) -> Layout:
    """The layout of this installation (or of the dev checkout)."""
    app = platform.app_dir()
    data_root = platform.program_data_dir() or Path.home() / ".paperless-win"
    override = os.environ.get("PAPERLESS_WIN_SERVICE_DIR")
    if override:
        service_dir = Path(override)
    elif (app / "service" / EXE_NAME).is_file() or not (app / ".tools").is_dir():
        service_dir = app / "service"  # installed layout
    else:
        service_dir = app / ".tools" / "service"  # dev checkout
    src = Path(__file__).resolve().parents[1]
    return Layout(
        app_dir=app,
        python=Path(sys.executable),
        src_dir=src,
        service_dir=service_dir,
        data_root=data_root,
        conf_path=Path(
            os.environ.get("PAPERLESS_CONFIGURATION_PATH")
            or data_root / "paperless.conf",
        ),
        log_dir=log_dir or data_root / "logs",
    )


def find_winsw(layout: Layout) -> Path | None:
    """Where a WinSW executable to copy from can be found (installed or dev layout)."""
    candidates = [
        layout.exe,
        layout.service_dir / WINSW_DEV_NAME,
        layout.app_dir / ".tools" / "winsw" / WINSW_DEV_NAME,
        layout.app_dir / "service" / WINSW_DEV_NAME,
    ]
    return next((c for c in candidates if c.is_file()), None)


# -- the WinSW configuration -------------------------------------------------------------------
def render_xml(
    layout: Layout,
    account: Account | None = None,
    *,
    delayed_start: bool = True,
) -> str:
    """The WinSW configuration for this layout and account (UTF-8 XML)."""
    account = account or Account.virtual()
    root = ET.Element("service")

    def add(tag: str, text: str | None = None, **attrs: str) -> ET.Element:
        element = ET.SubElement(root, tag, attrs)
        if text is not None:
            element.text = text
        return element

    add("id", SERVICE_ID)
    add("name", SERVICE_ID)
    add("description", DESCRIPTION)
    add("executable", str(layout.python))
    add("arguments", "-m paperless_win run")
    add("workingdirectory", str(layout.src_dir))
    # Stop by asking the supervisor, which drains workers and stops children in order. WinSW
    # waits `stoptimeout` for the main process to exit, then kills what is left.
    add("stopexecutable", str(layout.python))
    add(
        "stoparguments",
        f"-m paperless_win stop --timeout {STOP_COMMAND_TIMEOUT_SECONDS}",
    )
    add("stoptimeout", f"{STOP_TIMEOUT_SECONDS} sec")
    add("startmode", "Automatic")
    if delayed_start:
        add("delayedAutoStart", "true")
    # Restart after a failure (the supervisor exits non-zero when a child is in a crash loop),
    # waiting longer each time; forget the failures after an hour without one.
    add("onfailure", action="restart", delay="10 sec")
    add("onfailure", action="restart", delay="30 sec")
    add("onfailure", action="restart", delay="60 sec")
    add("resetfailure", "1 hour")
    add("logpath", str(layout.log_dir / "service"))
    log = add("log", mode="roll-by-size")
    ET.SubElement(log, "sizeThreshold").text = "10240"
    ET.SubElement(log, "keepFiles").text = "8"
    add("env", name="PAPERLESS_CONFIGURATION_PATH", value=str(layout.conf_path))
    add("env", name="PAPERLESS_WIN_APP_DIR", value=str(layout.app_dir))
    add("env", name="PYTHONUTF8", value="1")
    if os.environ.get("PAPERLESS_WIN_DATA_ROOT"):
        add(
            "env",
            name="PAPERLESS_WIN_DATA_ROOT",
            value=os.environ["PAPERLESS_WIN_DATA_ROOT"],
        )
    acct = add("serviceaccount")
    ET.SubElement(acct, "domain").text = account.domain
    ET.SubElement(acct, "user").text = account.user
    if account.kind == "user":
        if account.password is not None:
            ET.SubElement(acct, "password").text = account.password
        ET.SubElement(
            acct,
            "allowservicelogon",
        ).text = "true"  # grants "Log on as a service"
    ET.indent(root)
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        + ET.tostring(root, encoding="unicode")
        + "\n"
    )


# -- permissions ---------------------------------------------------------------------------------
def _grant(principal: str, rights: str) -> str:
    return f"{principal}:(OI)(CI){rights}"


def is_below(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def acl_commands(
    layout: Layout,
    account: Account,
    data_dirs: Mapping[str, Path],
) -> list[list[str]]:
    """The ``icacls`` calls that give every folder the right permissions.

    * ``data_root`` (``%ProgramData%\\paperless-win``): inheritance from ProgramData is cut (it
      would let every user read the data and ``paperless.conf``), then SYSTEM, Administrators and
      the service account get full control and nothing else.
    * the consume folder gets ``Modify`` for Users on top, so people can drop files in.
    * data folders elsewhere (another drive, a NAS) only get ``Modify`` for the service account,
      their other permissions stay as the owner set them.
    * the application folder gets read and execute for the service account.

    ``data_dirs`` maps ``"consume"`` and any number of other names to configured folders.
    """
    service = account.principal
    full = [_grant("*" + SID_SYSTEM, "F"), _grant("*" + SID_ADMINISTRATORS, "F")]
    if service not in {"*" + SID_SYSTEM}:
        full.append(_grant(service, "F"))
    commands: list[list[str]] = [
        ["icacls", str(layout.data_root), "/inheritance:r", "/grant:r", *full, "/Q"],
        # children created earlier (with the old, wider permissions) inherit from the root again
        ["icacls", str(layout.data_root / "*"), "/reset", "/T", "/C", "/Q"],
    ]
    consume = data_dirs.get("consume")
    for directory in data_dirs.values():
        if is_below(directory, layout.data_root):
            continue
        commands.append(
            ["icacls", str(directory), "/grant", _grant(service, "M"), "/Q"],
        )
    if consume is not None and is_below(consume, layout.data_root):
        commands.append(
            ["icacls", str(consume), "/grant", _grant("*" + SID_USERS, "M"), "/Q"],
        )
    commands.append(
        ["icacls", str(layout.app_dir), "/grant", _grant(service, "RX"), "/Q"],
    )
    return commands


def firewall_commands(port: int, *, remove: bool = False) -> list[str]:
    """``netsh`` call that opens (or closes) the web port for incoming connections."""
    if remove:
        return [
            "netsh",
            "advfirewall",
            "firewall",
            "delete",
            "rule",
            f"name={FIREWALL_RULE}",
        ]
    return [
        "netsh",
        "advfirewall",
        "firewall",
        "add",
        "rule",
        f"name={FIREWALL_RULE}",
        "dir=in",
        "action=allow",
        "protocol=TCP",
        f"localport={port}",
        "profile=private,domain",  # not on public networks
    ]


# -- acting on the machine ---------------------------------------------------------------------------
def is_admin() -> bool:
    if not platform.IS_WINDOWS:
        return os.geteuid() == 0  # type: ignore[attr-defined]
    import ctypes

    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        return False


class ServiceError(RuntimeError):
    """A service operation failed; the message is meant for the user."""


def run(
    argv: Iterable[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
    timeout: float | None = None,
) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(
            list(argv),
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as error:
        msg = f"{' '.join(str(a) for a in argv)} did not finish within {timeout:.0f} s"
        raise ServiceError(msg) from error
    if check and result.returncode != 0:
        detail = (result.stdout + result.stderr).strip()
        msg = f"{' '.join(str(a) for a in argv)} failed ({result.returncode}): {detail[-400:]}"
        raise ServiceError(msg)
    return result


def winsw(
    layout: Layout,
    command: str,
    *extra: str,
    check: bool = True,
    timeout: float | None = 300,
) -> subprocess.CompletedProcess:
    if not layout.exe.is_file():
        msg = f"{layout.exe} not found (the installer puts WinSW there; in a dev checkout run bootstrap-dev.ps1)"
        raise ServiceError(msg)
    return run(
        [str(layout.exe), command, *extra],
        cwd=layout.service_dir,
        check=check,
        timeout=timeout,
    )


def wait_for_state(state: str, timeout: float) -> bool:
    """Wait until the service is in ``state`` (``RUNNING``, ``STOPPED``). False after ``timeout`` seconds."""
    deadline = time.monotonic() + timeout
    while True:
        if service_state() == state:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.5)


def stop(layout: Layout, timeout: float = 120) -> None:
    """Stop the service and wait for it to be stopped.

    WinSW's own ``stopwait`` loops for as long as the service is not stopped, so a stuck service
    would block the caller for ever: ask with ``stop`` and look at the state ourselves.
    """
    if service_state() in (None, "STOPPED"):
        return
    winsw(layout, "stop", check=False, timeout=60)
    if not wait_for_state("STOPPED", timeout):
        msg = (
            f"The service did not stop within {timeout:.0f} s (state: {service_state()}). "
            f"Look at the logs in {layout.service_dir}."
        )
        raise ServiceError(msg)


def restart(layout: Layout, timeout: float = 120) -> None:
    """Stop the service (if it runs), start it again and wait until it runs."""
    stop(layout, timeout)
    winsw(layout, "start", timeout=60)
    if not wait_for_state("RUNNING", timeout):
        msg = f"The service did not start within {timeout:.0f} s (state: {service_state()})."
        raise ServiceError(msg)


def service_state() -> str | None:
    """``RUNNING``, ``STOPPED``, ``START_PENDING``... or ``None`` if the service is not installed."""
    result = run(["sc", "query", SERVICE_ID], check=False)
    if result.returncode == 1060:  # ERROR_SERVICE_DOES_NOT_EXIST
        return None
    for line in result.stdout.splitlines():
        parts = line.split()
        if parts and parts[0] == "STATE" and len(parts) >= 4:
            return parts[3]
    return None


def restrict_file(path: Path) -> None:
    """Only SYSTEM and Administrators may read ``path`` (it may hold a password for a moment)."""
    run(
        [
            "icacls",
            str(path),
            "/inheritance:r",
            "/grant:r",
            f"*{SID_SYSTEM}:F",
            f"*{SID_ADMINISTRATORS}:F",
            "/Q",
        ],
    )


def write_xml(layout: Layout, account: Account) -> None:
    layout.service_dir.mkdir(parents=True, exist_ok=True)
    if account.password is not None:
        layout.xml.touch()
        restrict_file(layout.xml)  # before the password is written
    layout.xml.write_text(render_xml(layout, account), encoding="utf-8")


def scrub_password(layout: Layout, account: Account) -> None:
    """WinSW only needs the password while installing; the SCM keeps it from then on."""
    if account.password is not None:
        layout.xml.write_text(
            render_xml(layout, Account(account.kind, account.domain, account.user)),
            encoding="utf-8",
        )


def install(
    layout: Layout,
    account: Account,
    data_dirs: Mapping[str, Path],
    *,
    force: bool = False,
    winsw_source: Path | None = None,
) -> None:
    if not is_admin():
        raise ServiceError(ERROR_NOT_ADMIN)
    if service_state() is not None:
        if not force:
            msg = "the service is already installed; use 'service uninstall' first, or --force"
            raise ServiceError(msg)
        uninstall(layout)
    layout.service_dir.mkdir(parents=True, exist_ok=True)
    if not layout.exe.is_file():
        source = winsw_source or find_winsw(layout)
        if source is None:
            msg = "WinSW not found: run windows\\scripts\\bootstrap-dev.ps1 or pass --winsw PATH"
            raise ServiceError(msg)
        shutil.copy2(source, layout.exe)
    layout.data_root.mkdir(parents=True, exist_ok=True)
    (layout.log_dir / "service").mkdir(parents=True, exist_ok=True)
    write_xml(layout, account)
    try:
        winsw(layout, "install")
    finally:
        scrub_password(layout, account)
    apply_acls(layout, account, data_dirs)


def apply_acls(layout: Layout, account: Account, data_dirs: Mapping[str, Path]) -> None:
    for argv in acl_commands(layout, account, data_dirs):
        run(argv)


def uninstall(layout: Layout) -> None:
    """Stop and remove the service. Data, logs and configuration are left untouched."""
    if not is_admin():
        raise ServiceError(ERROR_NOT_ADMIN)
    if service_state() is None:
        return
    try:
        stop(layout)
    except ServiceError:
        pass  # a stuck service is marked for deletion by the uninstall below
    winsw(layout, "uninstall")


def set_account(
    layout: Layout,
    account: Account,
    data_dirs: Mapping[str, Path],
) -> None:
    """Re-register the service under another account (for a NAS or domain share).

    A virtual account cannot authenticate to a network share, so a consume folder or media
    folder on a NAS needs a real local or domain user. The password is only held in the XML
    (readable by Administrators and SYSTEM only) while WinSW registers it.
    """
    was_running = service_state() == "RUNNING"
    install(layout, account, data_dirs, force=True)
    if was_running:
        winsw(layout, "start")


def firewall(port: int, *, remove: bool = False) -> None:
    if not is_admin():
        raise ServiceError(ERROR_NOT_ADMIN)
    if remove:
        run(firewall_commands(port, remove=True), check=False)
        return
    run(firewall_commands(port, remove=True), check=False)  # replace an older rule
    run(firewall_commands(port))
