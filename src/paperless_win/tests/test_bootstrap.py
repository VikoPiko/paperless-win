from __future__ import annotations

import os
from pathlib import Path

import pytest

from paperless_win import bootstrap
from paperless_win import platform
from paperless_win.tests.test_platform import fake_windows  # noqa: F401
from paperless_win.tests.test_platform import touch

MANAGED_ENV = ("MAGIC", "HOME", "PAPERLESS_THUMBNAIL_FONT_NAME", "PAPERLESS_OCR_CLEAN")


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
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
