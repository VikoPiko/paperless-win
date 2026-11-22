# ruff: noqa: INP001, T201
"""Send Ctrl-C to the console of another process: ``python send_ctrl_c.py <pid>``.

Used by supervisor-integration.ps1 to test a real Ctrl-C. The target must own its console
(started with ``Start-Process``); the supervisor's children have consoles of their own, so
only the supervisor receives it.
"""

import ctypes
import sys

CTRL_C_EVENT = 0


def main() -> int:
    pid = int(sys.argv[1])
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.FreeConsole()
    if not k32.AttachConsole(pid):
        print(f"AttachConsole({pid}) failed: {ctypes.get_last_error()}")
        return 1
    k32.SetConsoleCtrlHandler(None, True)  # noqa: FBT003  (do not die from our own event)
    if not k32.GenerateConsoleCtrlEvent(CTRL_C_EVENT, 0):
        print(f"GenerateConsoleCtrlEvent failed: {ctypes.get_last_error()}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
