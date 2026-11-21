from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest

from paperless_win import platform


@pytest.fixture
def fake_windows(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Pretend to be Windows with an empty app dir and an empty PATH."""
    app = tmp_path / "app"
    app.mkdir()
    monkeypatch.setattr(platform, "IS_WINDOWS", True)
    monkeypatch.setenv("PAPERLESS_WIN_APP_DIR", str(app))
    monkeypatch.setenv("PATH", str(tmp_path / "empty-path"))
    monkeypatch.setenv("PROGRAMDATA", str(tmp_path / "ProgramData"))
    for key in list(os.environ):
        if key.startswith("PAPERLESS_BIN_"):
            monkeypatch.delenv(key)
    if sys.platform != "win32":
        # Emulate PATHEXT so "tesseract" finds "tesseract.exe" when simulating Windows on
        # Linux. Without this, shutil.which() can only find extension-less, executable files.
        real_which = shutil.which

        def which_with_pathext(cmd, mode=os.F_OK | os.X_OK, path=None):
            return real_which(cmd, mode=os.F_OK, path=path) or real_which(
                f"{cmd}.exe",
                mode=os.F_OK,
                path=path,
            )

        monkeypatch.setattr(shutil, "which", which_with_pathext)
    return app


def touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    return path


def test_is_windows_matches_sys_platform() -> None:
    assert isinstance(platform.IS_WINDOWS, bool)
    assert (sys.platform == "win32") == platform.IS_WINDOWS


def test_linux_behaviour_is_upstream(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(platform, "IS_WINDOWS", False)
    monkeypatch.setenv("PAPERLESS_BIN_GS", "/definitely/not/here")  # ignored on Linux
    assert platform.config_search_paths() == []
    assert platform.program_data_dir() is None
    assert platform.bin_dirs() == []
    assert platform.find_binary("gs") == shutil.which("gs")
    assert platform.find_binary("no-such-binary-xyz") is None
    assert platform.default_font() == Path(
        "/usr/share/fonts/liberation/LiberationSerif-Regular.ttf",
    )


def test_app_dir_defaults_to_repo_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PAPERLESS_WIN_APP_DIR", raising=False)
    assert (platform.app_dir() / "src" / "paperless_win" / "platform.py").is_file()


def test_program_data_and_config_paths(fake_windows: Path, tmp_path: Path) -> None:
    assert platform.program_data_dir() == tmp_path / "ProgramData" / "paperless-win"
    assert platform.config_search_paths() == [
        tmp_path / "ProgramData" / "paperless-win" / "paperless.conf",
        fake_windows / "paperless.conf",
    ]


def test_default_tmp_dir_is_a_directory() -> None:
    assert platform.default_tmp_dir().is_dir()


def test_default_font_prefers_bundled(fake_windows: Path) -> None:
    bundled = touch(
        fake_windows / "windows" / "assets" / "fonts" / "LiberationSerif-Regular.ttf",
    )
    assert platform.default_font() == bundled


def test_default_font_falls_back_to_system_serif(
    fake_windows: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("WINDIR", str(tmp_path / "Win"))
    assert platform.default_font() == tmp_path / "Win" / "Fonts" / "times.ttf"


def test_find_binary_maps_gs_to_gswin64c(fake_windows: Path) -> None:
    exe = touch(fake_windows / "bin" / "ghostscript" / "bin" / "gswin64c.exe")
    assert platform.find_binary("gs") == str(exe)


def test_find_binary_adds_exe_suffix(fake_windows: Path) -> None:
    exe = touch(fake_windows / "bin" / "poppler" / "Library" / "bin" / "pdftoppm.exe")
    assert platform.find_binary("pdftoppm") == str(exe)
    assert platform.find_binary("pdfinfo") is None


def test_find_binary_env_override_wins(
    fake_windows: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    touch(fake_windows / "bin" / "ghostscript" / "bin" / "gswin64c.exe")
    custom = touch(tmp_path / "custom" / "my-gs.exe")
    monkeypatch.setenv("PAPERLESS_BIN_GS", str(custom))
    assert platform.find_binary("gs") == str(custom)


def test_find_binary_missing_override_does_not_fall_back(
    fake_windows: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    touch(fake_windows / "bin" / "tesseract" / "tesseract.exe")
    monkeypatch.setenv("PAPERLESS_BIN_TESSERACT", "does-not-exist.exe")
    assert platform.find_binary("tesseract") is None


def test_find_binary_bin_dir_env(
    fake_windows: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    exe = touch(tmp_path / "tools" / "tesseract" / "tesseract.exe")
    monkeypatch.setenv("PAPERLESS_BIN_DIR", str(tmp_path / "tools"))
    assert platform.find_binary("tesseract") == str(exe)


def test_find_binary_falls_back_to_path(
    fake_windows: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    exe = touch(tmp_path / "on-path" / "qpdf.exe")
    monkeypatch.setenv("PATH", str(tmp_path / "on-path"))
    monkeypatch.setenv("PATHEXT", ".EXE")
    found = platform.find_binary("qpdf")
    assert found is not None
    assert Path(found).resolve() == exe.resolve()


def test_bin_dirs_skips_download_and_tool_noise(fake_windows: Path) -> None:
    touch(fake_windows / ".tools" / "dl" / "installer.exe")
    touch(fake_windows / ".tools" / "7zip" / "Files" / "7-Zip" / "7z.exe")
    touch(fake_windows / ".tools" / "garnet" / "net10.0" / "GarnetServer.exe")
    touch(fake_windows / ".tools" / "garnet" / "net10.0" / "Service" / "worker.exe")
    touch(fake_windows / ".tools" / "libmagic" / "libmagic-1.dll")
    assert platform.bin_dirs() == [
        fake_windows / ".tools" / "libmagic",
        fake_windows / ".tools" / "garnet" / "net10.0",
    ]


def test_bin_dirs_is_empty_without_roots(fake_windows: Path) -> None:
    assert platform.bin_dirs() == []


def test_find_binary_trusts_path_when_dirs_already_on_it(
    fake_windows: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Once apply() has put the bin dirs on PATH, a (mocked) which() miss is final."""
    tools = fake_windows / "bin" / "tesseract"
    touch(tools / "tesseract.exe")
    monkeypatch.setenv("PATH", str(tools))
    monkeypatch.setattr(shutil, "which", lambda name, **kwargs: None)
    assert platform.find_binary("tesseract") is None


class TestGpg:
    def test_gpg_dirs_found_in_default_locations(
        self,
        fake_windows: Path,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        pf = tmp_path / "pf86"
        gpg_bin = pf / "GnuPG" / "bin"
        touch(gpg_bin / "gpg.exe")
        monkeypatch.setenv("ProgramFiles(x86)", str(pf))
        monkeypatch.delenv("ProgramFiles", raising=False)
        monkeypatch.delenv("LOCALAPPDATA", raising=False)
        assert platform.gpg_dirs() == [gpg_bin]
        assert platform.find_binary("gpg") == str(gpg_bin / "gpg.exe")

    def test_missing_gpg_is_not_an_error(
        self,
        fake_windows: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        for key in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
            monkeypatch.delenv(key, raising=False)
        assert platform.gpg_dirs() == []
        assert platform.find_binary("gpg") is None

    def test_linux_has_no_gpg_dirs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(platform, "IS_WINDOWS", False)
        assert platform.gpg_dirs() == []
