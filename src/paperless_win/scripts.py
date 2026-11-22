"""Run pre/post-consume scripts on Windows.

Upstream executes the configured script directly, which only works for executables.
``script_arguments`` rewrites the command from the script's extension; it is called by
``documents.utils.run_subprocess`` for every subprocess and leaves everything that is not
a script alone. The environment variables upstream sets (``DOCUMENT_*``, ``TASK_ID``) are
passed through unchanged, because only the argument list is rewritten.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from paperless_win import platform

SUPPORTED = ".ps1, .bat, .cmd, .py, .exe"


def powershell_command() -> str:
    """``pwsh`` (PowerShell 7) if installed, else Windows PowerShell 5.1."""
    found = platform.find_binary("pwsh")
    if found:
        return found
    root = os.environ.get("SYSTEMROOT") or r"C:\Windows"
    legacy = Path(root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    return (
        str(legacy)
        if legacy.is_file()
        else (platform.find_binary("powershell") or "powershell")
    )


def script_arguments(arguments: list[Any]) -> list[Any]:
    """Command line that actually runs ``arguments[0]`` on Windows (identity elsewhere).

    ``.ps1`` -> PowerShell ``-File``; ``.bat``/``.cmd`` -> ``cmd /c``; ``.py`` -> the current
    Python; ``.exe``/``.com`` and names without an extension (``pdftoppm``) -> unchanged.
    An existing file with any other extension raises ``ValueError`` with a clear message.
    """
    if not platform.IS_WINDOWS or not arguments:
        return arguments
    first = os.fspath(arguments[0])
    suffix = Path(first).suffix.lower()
    rest = list(arguments[1:])
    match suffix:
        case "" | ".exe" | ".com":
            return arguments
        case ".ps1":
            return [
                powershell_command(),
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                first,
                *rest,
            ]
        case ".bat" | ".cmd":
            return ["cmd.exe", "/d", "/c", first, *rest]
        case ".py":
            return [sys.executable, first, *rest]
        case _:
            if Path(first).is_file():
                msg = (
                    f"Cannot run '{first}' on Windows: '{suffix}' scripts are not supported. "
                    f"Use one of: {SUPPORTED}."
                )
                raise ValueError(msg)
            return arguments  # not a file: let the OS report "not found"
