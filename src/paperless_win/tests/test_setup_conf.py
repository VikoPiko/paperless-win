"""paperless.conf generation for the installer."""

from __future__ import annotations

from typing import TYPE_CHECKING

from paperless_win import ctl
from paperless_win import setup_conf

if TYPE_CHECKING:
    from pathlib import Path


def values(tmp_path: Path, **overrides) -> setup_conf.ConfValues:
    return setup_conf.ConfValues(data_dir=tmp_path / "data", **overrides)


def parse(text: str) -> dict[str, str]:
    return dict(
        line.split("=", 1)
        for line in text.splitlines()
        if line and not line.startswith("#")
    )


def test_conf_points_everything_at_the_data_dir(tmp_path: Path) -> None:
    conf = parse(setup_conf.render_conf(values(tmp_path), "key"))
    data = tmp_path / "data"
    assert conf["PAPERLESS_DATA_DIR"] == str(data)
    assert conf["PAPERLESS_MEDIA_ROOT"] == str(data / "media")
    assert conf["PAPERLESS_CONSUMPTION_DIR"] == str(data / "consume")
    assert conf["PAPERLESS_SCRATCH_DIR"] == str(data / "scratch")
    assert conf["PAPERLESS_STATICDIR"] == str(
        data / "static",
    )  # writable: collectstatic runs at init
    assert conf["PAPERLESS_LOGGING_DIR"] == str(data / "logs")
    assert conf["PAPERLESS_REDIS"] == "redis://127.0.0.1:6379"
    assert conf["PAPERLESS_SECRET_KEY"] == "key"


def test_conf_is_local_only_by_default(tmp_path: Path) -> None:
    conf = parse(setup_conf.render_conf(values(tmp_path), "key"))
    assert conf["PAPERLESS_BIND_ADDR"] == "127.0.0.1"
    assert conf["PAPERLESS_PORT"] == "8000"


def test_conf_takes_the_chosen_folders_languages_and_ports(tmp_path: Path) -> None:
    custom = setup_conf.ConfValues(
        data_dir=tmp_path / "d",
        consume_dir=tmp_path / "inbox",
        media_dir=tmp_path / "nas" / "media",
        ocr_languages="eng+deu",
        port=8123,
        bind="0.0.0.0",
        redis_port=6400,
        extra={"PAPERLESS_TIME_ZONE": "Europe/Berlin"},
    )
    conf = parse(setup_conf.render_conf(custom, "key"))
    assert conf["PAPERLESS_CONSUMPTION_DIR"] == str(tmp_path / "inbox")
    assert conf["PAPERLESS_MEDIA_ROOT"] == str(tmp_path / "nas" / "media")
    assert conf["PAPERLESS_OCR_LANGUAGE"] == "eng+deu"
    assert conf["PAPERLESS_PORT"] == "8123"
    assert conf["PAPERLESS_BIND_ADDR"] == "0.0.0.0"
    assert conf["PAPERLESS_REDIS"] == "redis://127.0.0.1:6400"
    assert conf["PAPERLESS_TIME_ZONE"] == "Europe/Berlin"


def test_the_admin_password_never_goes_into_the_conf(tmp_path: Path) -> None:
    text = setup_conf.render_conf(values(tmp_path), "key")
    assert "PASSWORD" not in text
    assert "ADMIN" not in text


def test_secret_keys_are_random_and_long() -> None:
    first, second = setup_conf.new_secret_key(), setup_conf.new_secret_key()
    assert first != second
    assert len(first) >= 50


def test_conf_is_created_once_and_left_alone_on_upgrade(tmp_path: Path) -> None:
    conf = tmp_path / "ProgramData" / "paperless.conf"
    assert setup_conf.write_conf(conf, values(tmp_path)) == "created"
    first = conf.read_text(encoding="utf-8")
    conf.write_text(
        first + "PAPERLESS_TIME_ZONE=Europe/Paris\n",
        encoding="utf-8",
    )  # user edit
    assert setup_conf.write_conf(conf, values(tmp_path, port=9999)) == "kept"
    assert "PAPERLESS_TIME_ZONE=Europe/Paris" in conf.read_text(encoding="utf-8")
    assert "PAPERLESS_PORT=9999" not in conf.read_text(encoding="utf-8")


def test_force_rewrites_but_keeps_the_secret_key(tmp_path: Path) -> None:
    conf = tmp_path / "paperless.conf"
    setup_conf.write_conf(conf, values(tmp_path))
    secret = setup_conf.existing_secret_key(conf)
    assert secret
    assert (
        setup_conf.write_conf(conf, values(tmp_path, port=9999), force=True)
        == "rewritten"
    )
    assert setup_conf.existing_secret_key(conf) == secret
    assert "PAPERLESS_PORT=9999" in conf.read_text(encoding="utf-8")


def test_existing_secret_key_of_a_missing_file(tmp_path: Path) -> None:
    assert setup_conf.existing_secret_key(tmp_path / "nope.conf") is None


def test_admin_password_file_is_read_and_deleted(tmp_path: Path) -> None:
    secret = tmp_path / "pw.txt"
    secret.write_bytes("﻿päss w0rd!\r\n".encode())  # BOM, spaces, non-ASCII, CRLF
    assert setup_conf.read_admin_password(secret) == "päss w0rd!"
    assert not secret.exists()


def test_setup_command_writes_the_conf(tmp_path: Path, capsys) -> None:
    conf = tmp_path / "pd" / "paperless.conf"
    code = ctl.main(
        [
            "setup",
            "--data-dir",
            str(tmp_path / "data"),
            "--conf",
            str(conf),
            "--ocr-languages",
            "eng+deu",
            "--port",
            "8080",
        ],
    )
    assert code == 0
    assert "created" in capsys.readouterr().out
    text = conf.read_text(encoding="utf-8")
    assert "PAPERLESS_OCR_LANGUAGE=eng+deu" in text
    assert "PAPERLESS_PORT=8080" in text
    assert (
        ctl.main(["setup", "--data-dir", str(tmp_path / "data"), "--conf", str(conf)])
        == 0
    )
    assert "kept" in capsys.readouterr().out
