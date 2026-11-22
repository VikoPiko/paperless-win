from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from paperless_win import bootstrap
from paperless_win import fs
from paperless_win import platform
from paperless_win.tests.test_platform import fake_windows  # noqa: F401
from paperless_win.tests.test_platform import touch

MANAGED_ENV = ("MAGIC", "HOME", "PAPERLESS_THUMBNAIL_FONT_NAME", "PAPERLESS_OCR_CLEAN")


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # apply() writes os.environ directly: work on a private copy so nothing leaks
    monkeypatch.setattr(os, "environ", os.environ.copy())
    for key in MANAGED_ENV:
        monkeypatch.delenv(key, raising=False)


def test_noop_on_linux(monkeypatch: pytest.MonkeyPatch, clean_env: None) -> None:
    monkeypatch.setattr(platform, "IS_WINDOWS", False)
    before = dict(os.environ)
    bootstrap.apply()
    assert dict(os.environ) == before


def test_puts_tool_dirs_on_path(fake_windows: Path, clean_env: None) -> None:  # noqa: F811
    gs = fake_windows / "bin" / "ghostscript" / "bin"
    touch(gs / "gswin64c.exe")
    bootstrap.apply()
    assert str(gs) in os.environ["PATH"].split(os.pathsep)


def test_path_entries_are_not_duplicated(fake_windows: Path, clean_env: None) -> None:  # noqa: F811
    touch(fake_windows / "bin" / "tesseract" / "tesseract.exe")
    bootstrap.apply()
    first = os.environ["PATH"]
    bootstrap.apply()
    assert os.environ["PATH"] == first


def test_sets_magic_when_database_present(fake_windows: Path, clean_env: None) -> None:  # noqa: F811
    libmagic = fake_windows / "bin" / "libmagic"
    touch(libmagic / "libmagic-1.dll")
    mgc = touch(libmagic / "magic.mgc")
    bootstrap.apply()
    assert os.environ["MAGIC"] == str(mgc)


def test_does_not_override_explicit_settings(
    fake_windows: Path,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    clean_env: None,
) -> None:
    monkeypatch.setenv("MAGIC", "custom.mgc")
    monkeypatch.setenv("HOME", "C:/home")
    monkeypatch.setenv("PAPERLESS_OCR_CLEAN", "clean")
    monkeypatch.setenv("PAPERLESS_THUMBNAIL_FONT_NAME", "x.ttf")
    touch(fake_windows / "bin" / "libmagic" / "magic.mgc")
    touch(fake_windows / "bin" / "libmagic" / "libmagic-1.dll")
    bootstrap.apply()
    assert os.environ["MAGIC"] == "custom.mgc"
    assert os.environ["HOME"] == "C:/home"
    assert os.environ["PAPERLESS_OCR_CLEAN"] == "clean"
    assert os.environ["PAPERLESS_THUMBNAIL_FONT_NAME"] == "x.ttf"


def test_ocr_clean_defaults_to_none_without_unpaper(
    fake_windows: Path,  # noqa: F811
    clean_env: None,
) -> None:
    bootstrap.apply()
    assert os.environ["PAPERLESS_OCR_CLEAN"] == "none"


def test_ocr_clean_keeps_upstream_default_with_unpaper(
    fake_windows: Path,  # noqa: F811
    clean_env: None,
) -> None:
    touch(fake_windows / "bin" / "unpaper" / "unpaper.exe")
    bootstrap.apply()
    assert "PAPERLESS_OCR_CLEAN" not in os.environ


def test_home_and_font_defaults(fake_windows: Path, clean_env: None) -> None:  # noqa: F811
    font = touch(
        fake_windows / "windows" / "assets" / "fonts" / "LiberationSerif-Regular.ttf",
    )
    bootstrap.apply()
    assert Path(os.environ["HOME"]) == platform.default_tmp_dir()
    assert os.environ["PAPERLESS_THUMBNAIL_FONT_NAME"] == str(font)


class TestConsumerDefaults:
    def test_windows_ignore_patterns_are_added(
        self,
        fake_windows: Path,  # noqa: F811
        clean_env: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("PAPERLESS_CONSUMER_IGNORE_PATTERNS", raising=False)
        bootstrap.apply()
        patterns = json.loads(os.environ["PAPERLESS_CONSUMER_IGNORE_PATTERNS"])
        assert r"^~\$.*" in patterns
        assert r".*\.crdownload$" in patterns
        for junk in ("~$report.docx", "scan.tmp", "scan.pdf.part", "f.crdownload"):
            assert any(re.match(p, junk) for p in patterns), junk
        for fine in ("report.docx", "invoice.pdf", "tmp.pdf"):
            assert not any(re.match(p, fine) for p in patterns), fine

    def test_user_patterns_are_kept_and_not_duplicated(
        self,
        fake_windows: Path,  # noqa: F811
        clean_env: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv(
            "PAPERLESS_CONSUMER_IGNORE_PATTERNS",
            json.dumps([r"^draft_.*", r"^~\$.*"]),
        )
        bootstrap.apply()
        bootstrap.apply()
        patterns = json.loads(os.environ["PAPERLESS_CONSUMER_IGNORE_PATTERNS"])
        assert patterns[0] == r"^draft_.*"
        assert patterns.count(r"^~\$.*") == 1
        assert len(patterns) == len(set(patterns))

    def test_invalid_user_value_is_left_alone(
        self,
        fake_windows: Path,  # noqa: F811
        clean_env: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("PAPERLESS_CONSUMER_IGNORE_PATTERNS", "not json")
        bootstrap.apply()
        assert os.environ["PAPERLESS_CONSUMER_IGNORE_PATTERNS"] == "not json"

    def test_network_share_defaults_to_polling(
        self,
        fake_windows: Path,  # noqa: F811
        clean_env: None,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.setenv("PAPERLESS_CONSUMPTION_DIR", "\\\\nas\\scans")
        monkeypatch.delenv("PAPERLESS_CONSUMER_POLLING_INTERVAL", raising=False)
        with caplog.at_level("INFO", logger="paperless.winport"):
            bootstrap.apply()
        assert os.environ["PAPERLESS_CONSUMER_POLLING_INTERVAL"] == "10"
        assert "network share" in caplog.text

    def test_explicit_polling_setting_wins(
        self,
        fake_windows: Path,  # noqa: F811
        clean_env: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("PAPERLESS_CONSUMPTION_DIR", "\\\\nas\\scans")
        monkeypatch.setenv("PAPERLESS_CONSUMER_POLLING_INTERVAL", "0")
        bootstrap.apply()
        assert os.environ["PAPERLESS_CONSUMER_POLLING_INTERVAL"] == "0"

    def test_local_folder_keeps_native_events(
        self,
        fake_windows: Path,  # noqa: F811
        clean_env: None,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setenv("PAPERLESS_CONSUMPTION_DIR", str(tmp_path))
        monkeypatch.delenv("PAPERLESS_CONSUMER_POLLING_INTERVAL", raising=False)
        monkeypatch.setattr(fs, "is_network_path", lambda path: False)
        bootstrap.apply()
        assert "PAPERLESS_CONSUMER_POLLING_INTERVAL" not in os.environ
