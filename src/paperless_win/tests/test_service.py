"""Service configuration, ACL plan and firewall commands: pure functions, tested on every OS."""

from __future__ import annotations

from typing import TYPE_CHECKING
from xml.etree import ElementTree as ET

import pytest

from paperless_win import service

if TYPE_CHECKING:
    from pathlib import Path


def layout(tmp_path: Path) -> service.Layout:
    return service.Layout(
        app_dir=tmp_path / "app",
        python=tmp_path / "app" / "python" / "python.exe",
        src_dir=tmp_path / "app" / "src",
        service_dir=tmp_path / "app" / "service",
        data_root=tmp_path / "ProgramData" / "paperless-win",
        conf_path=tmp_path / "ProgramData" / "paperless-win" / "paperless.conf",
        log_dir=tmp_path / "ProgramData" / "paperless-win" / "logs",
    )


def parse(xml: str) -> ET.Element:
    return ET.fromstring(xml)


def test_virtual_account_sid_matches_what_windows_reports() -> None:
    # values from `sc showsid` on Windows 11
    assert service.virtual_account_sid("wuauserv") == (
        "S-1-5-80-1014140700-3308905587-3330345912-272242898-93311788"
    )
    assert service.virtual_account_sid("paperless-win") == (
        "S-1-5-80-3527482016-480227831-1737430796-3343009422-3571622303"
    )
    assert service.virtual_account_sid("PAPERLESS-WIN") == service.virtual_account_sid(
        "paperless-win",
    )


def test_xml_runs_the_supervisor_and_stops_it_by_asking(tmp_path: Path) -> None:
    root = parse(service.render_xml(layout(tmp_path)))
    assert root.tag == "service"
    assert root.findtext("id") == "paperless-win"
    assert root.findtext("executable") == str(layout(tmp_path).python)
    assert root.findtext("arguments") == "-m paperless_win run"
    assert root.findtext("workingdirectory") == str(layout(tmp_path).src_dir)
    assert root.findtext("stopexecutable") == str(layout(tmp_path).python)
    assert root.findtext("stoparguments") == "-m paperless_win stop --timeout 25"
    assert root.findtext("stoptimeout") == "30 sec"


def test_xml_starts_at_boot_delayed_and_restarts_after_failures(tmp_path: Path) -> None:
    root = parse(service.render_xml(layout(tmp_path)))
    assert root.findtext("startmode") == "Automatic"
    assert root.findtext("delayedAutoStart") == "true"
    actions = [(e.get("action"), e.get("delay")) for e in root.findall("onfailure")]
    assert actions == [
        ("restart", "10 sec"),
        ("restart", "30 sec"),
        ("restart", "60 sec"),
    ]
    assert root.findtext("resetfailure") == "1 hour"


def test_xml_without_delayed_start(tmp_path: Path) -> None:
    root = parse(service.render_xml(layout(tmp_path), delayed_start=False))
    assert root.find("delayedAutoStart") is None


def test_xml_logs_roll_by_size_under_the_log_folder(tmp_path: Path) -> None:
    root = parse(service.render_xml(layout(tmp_path)))
    assert root.findtext("logpath") == str(layout(tmp_path).log_dir / "service")
    log = root.find("log")
    assert log is not None
    assert log.get("mode") == "roll-by-size"
    assert log.findtext("keepFiles") == "8"


def test_xml_environment(tmp_path: Path) -> None:
    lay = layout(tmp_path)
    env = {
        e.get("name"): e.get("value")
        for e in parse(service.render_xml(lay)).findall("env")
    }
    assert env["PAPERLESS_CONFIGURATION_PATH"] == str(lay.conf_path)
    assert env["PAPERLESS_WIN_APP_DIR"] == str(lay.app_dir)
    assert env["PYTHONUTF8"] == "1"


def test_xml_default_account_is_the_virtual_service_account(tmp_path: Path) -> None:
    account = parse(service.render_xml(layout(tmp_path))).find("serviceaccount")
    assert account is not None
    assert account.findtext("domain") == "NT SERVICE"
    assert account.findtext("user") == "paperless-win"
    assert account.find("password") is None
    assert account.find("allowservicelogon") is None


def test_xml_for_a_domain_user_carries_the_password_and_the_logon_right(
    tmp_path: Path,
) -> None:
    acct = service.Account.parse("CORP\\svc-paperless", "p&ss<word>")
    root = parse(service.render_xml(layout(tmp_path), acct))
    node = root.find("serviceaccount")
    assert node is not None
    assert node.findtext("domain") == "CORP"
    assert node.findtext("user") == "svc-paperless"
    assert (
        node.findtext("password") == "p&ss<word>"
    )  # escaped on the way out, intact on the way in
    assert node.findtext("allowservicelogon") == "true"


def test_the_password_is_not_in_the_scrubbed_xml(tmp_path: Path) -> None:
    lay = layout(tmp_path)
    lay.service_dir.mkdir(parents=True)
    acct = service.Account.parse("CORP\\svc", "secret-value")
    lay.xml.write_text(service.render_xml(lay, acct), encoding="utf-8")
    assert "secret-value" in lay.xml.read_text(encoding="utf-8")
    service.scrub_password(lay, acct)
    assert "secret-value" not in lay.xml.read_text(encoding="utf-8")


def test_xml_for_localsystem(tmp_path: Path) -> None:
    node = parse(service.render_xml(layout(tmp_path), service.Account.system())).find(
        "serviceaccount",
    )
    assert node is not None
    assert (node.findtext("domain"), node.findtext("user")) == (
        "NT AUTHORITY",
        "SYSTEM",
    )


@pytest.mark.parametrize(
    ("text", "kind", "domain", "user"),
    [
        ("virtual", "virtual", "NT SERVICE", "paperless-win"),
        ("NT SERVICE\\paperless-win", "virtual", "NT SERVICE", "paperless-win"),
        ("system", "system", "NT AUTHORITY", "SYSTEM"),
        ("LocalSystem", "system", "NT AUTHORITY", "SYSTEM"),
        ("CORP\\anna", "user", "CORP", "anna"),
        (".\\anna", "user", ".", "anna"),
        ("anna@corp.example", "user", "corp.example", "anna"),
        ("anna", "user", ".", "anna"),
    ],
)
def test_account_parsing(text: str, kind: str, domain: str, user: str) -> None:
    account = service.Account.parse(text)
    assert (account.kind, account.domain, account.user) == (kind, domain, user)


def test_account_parsing_rejects_nothing_after_the_domain() -> None:
    with pytest.raises(ValueError, match="not a valid account"):
        service.Account.parse("CORP\\")


def test_account_principals_for_icacls() -> None:
    assert service.Account.virtual().principal == "*" + service.virtual_account_sid()
    assert service.Account.system().principal == "*S-1-5-18"
    assert service.Account.parse("CORP\\anna").principal == "CORP\\anna"


def names(commands: list[list[str]]) -> list[str]:
    return [" ".join(c) for c in commands]


def test_data_root_is_locked_down_to_system_admins_and_the_service(
    tmp_path: Path,
) -> None:
    lay = layout(tmp_path)
    commands = service.acl_commands(
        lay,
        service.Account.virtual(),
        {"consume": lay.data_root / "consume"},
    )
    first = commands[0]
    assert first[:2] == ["icacls", str(lay.data_root)]
    assert (
        "/inheritance:r" in first
    )  # no more ProgramData defaults (Users could read everything)
    assert "/grant:r" in first
    grants = [a for a in first if ":(OI)(CI)" in a]
    assert grants == [
        "*S-1-5-18:(OI)(CI)F",
        "*S-1-5-32-544:(OI)(CI)F",
        f"*{service.virtual_account_sid()}:(OI)(CI)F",
    ]
    assert not any("S-1-5-32-545" in a for a in first)  # Users: nothing on the root
    assert commands[1][2:3] == ["/reset"]


def test_users_may_only_write_to_the_consume_folder(tmp_path: Path) -> None:
    lay = layout(tmp_path)
    dirs = {
        "data": lay.data_root / "data",
        "media": lay.data_root / "media",
        "consume": lay.data_root / "consume",
    }
    commands = service.acl_commands(lay, service.Account.virtual(), dirs)
    users = [c for c in commands if any("S-1-5-32-545" in a for a in c)]
    assert len(users) == 1
    assert users[0][1] == str(lay.data_root / "consume")
    assert "*S-1-5-32-545:(OI)(CI)M" in users[0]


def test_folders_outside_the_data_root_only_get_the_service_account(
    tmp_path: Path,
) -> None:
    lay = layout(tmp_path)
    nas = tmp_path / "nas" / "documents"
    dirs = {"media": nas, "consume": tmp_path / "nas" / "inbox"}
    commands = service.acl_commands(lay, service.Account.virtual(), dirs)
    assert any(
        c[1] == str(nas) and f"*{service.virtual_account_sid()}:(OI)(CI)M" in c
        for c in commands
    )
    assert not any(
        any("S-1-5-32-545" in a for a in c) for c in commands
    )  # foreign folders keep their rules
    assert not any("/inheritance:r" in c and c[1] == str(nas) for c in commands)


def test_service_account_can_read_the_application_folder(tmp_path: Path) -> None:
    lay = layout(tmp_path)
    last = service.acl_commands(lay, service.Account.virtual(), {})[-1]
    assert last[1] == str(lay.app_dir)
    assert f"*{service.virtual_account_sid()}:(OI)(CI)RX" in last


def test_acls_for_a_domain_user_use_its_name(tmp_path: Path) -> None:
    lay = layout(tmp_path)
    commands = service.acl_commands(lay, service.Account.parse("CORP\\anna"), {})
    assert "CORP\\anna:(OI)(CI)F" in commands[0]


def test_localsystem_is_not_granted_twice(tmp_path: Path) -> None:
    lay = layout(tmp_path)
    first = service.acl_commands(lay, service.Account.system(), {})[0]
    assert first.count("*S-1-5-18:(OI)(CI)F") == 1


def test_firewall_rule_is_for_the_private_and_domain_profiles(tmp_path: Path) -> None:
    add = service.firewall_commands(8000)
    assert add[:5] == ["netsh", "advfirewall", "firewall", "add", "rule"]
    assert "localport=8000" in add
    assert "profile=private,domain" in add  # never on a public network
    assert "dir=in" in add
    remove = service.firewall_commands(8000, remove=True)
    assert remove[3:5] == ["delete", "rule"]
    assert f"name={service.FIREWALL_RULE}" in remove


def test_dev_checkout_keeps_the_service_files_inside_the_ignored_tools_folder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".tools").mkdir()
    monkeypatch.setenv("PAPERLESS_WIN_APP_DIR", str(tmp_path))
    monkeypatch.delenv("PAPERLESS_WIN_SERVICE_DIR", raising=False)
    assert service.default_layout().service_dir == tmp_path / ".tools" / "service"


def test_installed_layout_uses_the_service_folder_next_to_the_app(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "service").mkdir()
    (tmp_path / "service" / service.EXE_NAME).write_bytes(b"x")
    (tmp_path / ".tools").mkdir()  # even if a .tools folder exists
    monkeypatch.setenv("PAPERLESS_WIN_APP_DIR", str(tmp_path))
    monkeypatch.delenv("PAPERLESS_WIN_SERVICE_DIR", raising=False)
    assert service.default_layout().service_dir == tmp_path / "service"


def test_winsw_is_found_in_the_dev_tools_folder(tmp_path: Path) -> None:
    lay = layout(tmp_path)
    assert service.find_winsw(lay) is None
    tools = lay.app_dir / ".tools" / "winsw"
    tools.mkdir(parents=True)
    (tools / service.WINSW_DEV_NAME).write_bytes(b"x")
    assert service.find_winsw(lay) == tools / service.WINSW_DEV_NAME


def test_install_refuses_without_administrator_rights(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(service, "is_admin", lambda: False)
    with pytest.raises(service.ServiceError, match="elevated prompt"):
        service.install(layout(tmp_path), service.Account.virtual(), {})
    with pytest.raises(service.ServiceError, match="elevated prompt"):
        service.uninstall(layout(tmp_path))
    with pytest.raises(service.ServiceError, match="elevated prompt"):
        service.firewall(8000)


def test_data_root_override_reaches_the_service_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PAPERLESS_WIN_DATA_ROOT", str(tmp_path / "other-root"))
    env = {
        e.get("name"): e.get("value")
        for e in parse(service.render_xml(layout(tmp_path))).findall("env")
    }
    assert env["PAPERLESS_WIN_DATA_ROOT"] == str(tmp_path / "other-root")
    monkeypatch.delenv("PAPERLESS_WIN_DATA_ROOT")
    env = {
        e.get("name"): e.get("value")
        for e in parse(service.render_xml(layout(tmp_path))).findall("env")
    }
    assert "PAPERLESS_WIN_DATA_ROOT" not in env
