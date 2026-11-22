from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from documents.utils import run_subprocess
from paperless_win import platform
from paperless_win import scripts

windows_only = pytest.mark.skipif(
    sys.platform != "win32",
    reason="runs real Windows scripts",
)


@pytest.fixture
def windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(platform, "IS_WINDOWS", True)


class TestArguments:
    def test_linux_is_identity(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(platform, "IS_WINDOWS", False)
        args = ["/opt/s.ps1", "x"]
        assert scripts.script_arguments(args) is args

    @pytest.mark.parametrize(
        "args",
        [["pdftoppm", "-png"], ["tesseract.exe", "a"], ["C:/x/gs.COM"], []],
    )
    def test_executables_and_bare_names_are_untouched(
        self,
        windows: None,
        args: list,
    ) -> None:
        assert scripts.script_arguments(args) == args

    def test_ps1_uses_powershell_file(
        self,
        windows: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(scripts, "powershell_command", lambda: "pwsh.exe")
        assert scripts.script_arguments(["C:/s/post.PS1", "a"]) == [
            "pwsh.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "C:/s/post.PS1", "a",
        ]  # fmt: skip

    @pytest.mark.parametrize("name", ["x.bat", "X.CMD"])
    def test_batch_files_use_cmd(self, windows: None, name: str) -> None:
        assert scripts.script_arguments([name, "a"]) == [
            "cmd.exe",
            "/d",
            "/c",
            name,
            "a",
        ]

    def test_python_uses_the_current_interpreter(self, windows: None) -> None:
        assert scripts.script_arguments(["s.py"]) == [sys.executable, "s.py"]

    def test_unknown_extension_of_an_existing_file_is_a_clear_error(
        self,
        windows: None,
        tmp_path: Path,
    ) -> None:
        script = tmp_path / "hook.vbs"
        script.write_text("x", encoding="utf-8")
        with pytest.raises(
            ValueError,
            match=r"'\.vbs' scripts are not supported.*\.ps1",
        ):
            scripts.script_arguments([str(script)])

    def test_unknown_extension_of_a_missing_file_is_left_to_the_os(
        self,
        windows: None,
    ) -> None:
        assert scripts.script_arguments(["missing.vbs"]) == ["missing.vbs"]

    def test_powershell_falls_back_to_windows_powershell(
        self,
        windows: None,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        legacy = tmp_path / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        legacy.parent.mkdir(parents=True)
        legacy.write_bytes(b"")
        monkeypatch.setattr(platform, "find_binary", lambda name: None)
        monkeypatch.setenv("SYSTEMROOT", str(tmp_path))
        assert scripts.powershell_command() == str(legacy)


ENV = {"DOCUMENT_ID": "42", "DOCUMENT_FILE_NAME": "Rechnung ü.pdf", "TASK_ID": "t-1"}


def run_script(path: Path, *, env: dict | None = None) -> subprocess.CompletedProcess:
    return run_subprocess([str(path)], {**os.environ, **ENV, **(env or {})})


@windows_only
class TestRealScripts:
    def test_powershell_script_gets_the_environment(self, tmp_path: Path) -> None:
        script = tmp_path / "dir with spaces" / "post.ps1"
        script.parent.mkdir()
        script.write_text(
            'Write-Output "id=$env:DOCUMENT_ID name=$env:DOCUMENT_FILE_NAME"',
            encoding="utf-8",
        )
        out = run_script(script).stdout.decode("utf-8", errors="replace")
        assert "id=42" in out
        assert "name=Rechnung" in out

    def test_batch_script_gets_the_environment(self, tmp_path: Path) -> None:
        script = tmp_path / "post.bat"
        script.write_text(
            "@echo off\necho id=%DOCUMENT_ID% task=%TASK_ID%\n",
            encoding="ascii",
        )
        assert b"id=42 task=t-1" in run_script(script).stdout

    def test_python_script_gets_the_environment(self, tmp_path: Path) -> None:
        script = tmp_path / "post.py"
        script.write_text(
            "import os; print('id=' + os.environ['DOCUMENT_ID'])",
            encoding="utf-8",
        )
        assert b"id=42" in run_script(script).stdout

    @pytest.mark.parametrize(
        ("name", "body"),
        [
            ("fail.ps1", "exit 7"),
            ("fail.bat", "@echo off\nexit /b 7\n"),
            ("fail.py", "import sys; sys.exit(7)"),
        ],
    )
    def test_non_zero_exit_codes_fail_the_call(
        self,
        tmp_path: Path,
        name: str,
        body: str,
    ) -> None:
        script = tmp_path / name
        script.write_text(body, encoding="ascii")
        with pytest.raises(subprocess.CalledProcessError) as caught:
            run_script(script)
        assert caught.value.returncode == 7

    def test_shipped_examples_run(self) -> None:
        examples = Path(__file__).resolve().parents[3] / "windows" / "examples"
        for name in ("post-consume.ps1", "post-consume.cmd", "post-consume.py"):
            assert b"42" in run_script(examples / name).stdout, name
