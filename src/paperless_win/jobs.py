"""Process trees that die together: Windows Job Objects (plain ctypes, no extra dependency).

Every supervised child gets its own job object with ``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE``:

* ``terminate()`` kills the child *and everything it started* (tesseract, ghostscript...),
  which ``Popen.kill()`` does not.
* If the supervisor itself dies, Windows closes its job handles and kills all children, so
  nothing is left orphaned.

Jobs can be nested (Windows 8 and later), so this also works when the supervisor was
started inside another job (a console host, a service wrapper, CI).

On other platforms the same interface is backed by process groups so the supervisor logic
and its tests run everywhere.
"""

from __future__ import annotations

import contextlib
import logging
import os
import signal
import subprocess
import sys

from paperless_win import platform

logger = logging.getLogger("paperless.winport.jobs")

_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_PROCESS_SET_QUOTA = 0x0100
_PROCESS_TERMINATE = 0x0001

CREATE_NO_WINDOW = 0x08000000


def _win_structures():
    """The few Win32 structures needed, built lazily so Linux never touches ctypes.wintypes."""
    import ctypes
    from ctypes import wintypes

    class IoCounters(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class BasicLimits(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", BasicLimits),
            ("IoInfo", IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    return ExtendedLimits


class WindowsJob:
    """A job object that kills its whole process tree when terminated or closed."""

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        self._ctypes = ctypes
        self._k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32 = self._k32
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        k32.SetInformationJobObject.restype = wintypes.BOOL
        k32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.LPVOID,
            wintypes.DWORD,
        ]
        k32.AssignProcessToJobObject.restype = wintypes.BOOL
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        k32.TerminateJobObject.restype = wintypes.BOOL
        k32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]

        self._handle = k32.CreateJobObjectW(None, None)
        if not self._handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = _win_structures()()
        limits.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        ok = k32.SetInformationJobObject(
            self._handle,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(limits),
            ctypes.sizeof(limits),
        )
        if not ok:
            error = ctypes.WinError(ctypes.get_last_error())
            self.close()
            raise error

    def assign(self, pid: int) -> None:
        """Put the process with this id (and so its future children) into the job."""
        process = self._k32.OpenProcess(
            _PROCESS_SET_QUOTA | _PROCESS_TERMINATE,
            False,  # noqa: FBT003
            pid,
        )
        if not process:
            raise self._ctypes.WinError(self._ctypes.get_last_error())
        try:
            if not self._k32.AssignProcessToJobObject(self._handle, process):
                raise self._ctypes.WinError(self._ctypes.get_last_error())
        finally:
            self._k32.CloseHandle(process)

    def terminate(self) -> None:
        """Kill every process in the job. Safe to call twice."""
        if self._handle:
            self._k32.TerminateJobObject(self._handle, 1)

    def close(self) -> None:
        """Release the handle; with KILL_ON_JOB_CLOSE this also kills what is left."""
        if self._handle:
            self._k32.CloseHandle(self._handle)
            self._handle = None


class PosixGroup:
    """Stand-in for a job: the child leads its own process group (tests and Linux)."""

    def __init__(self) -> None:
        self._pid: int | None = None

    def assign(self, pid: int) -> None:
        self._pid = pid

    def terminate(self) -> None:
        if self._pid is None:
            return
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(self._pid, signal.SIGKILL)  # type: ignore[attr-defined]

    def close(self) -> None:
        self.terminate()


def new_job() -> WindowsJob | PosixGroup:
    return WindowsJob() if platform.IS_WINDOWS else PosixGroup()


def popen_kwargs() -> dict:
    """Extra ``Popen`` arguments so the child can be killed as a tree.

    Windows: no console window (the supervisor may be a service). POSIX: own session.
    """
    if sys.platform == "win32":
        return {"creationflags": CREATE_NO_WINDOW}
    return {"start_new_session": True}


def launch(
    argv: list[str],
    **kwargs,
) -> tuple[subprocess.Popen, WindowsJob | PosixGroup]:
    """Start ``argv`` and put it into a fresh job. The job is closed if that fails."""
    job = new_job()
    process: subprocess.Popen | None = None
    try:
        process = subprocess.Popen(argv, **{**popen_kwargs(), **kwargs})
        job.assign(process.pid)
    except BaseException:
        if process is not None:
            process.kill()
        job.close()
        raise
    return process, job


def pid_alive(pid: int) -> bool:
    """Is there a running process with this id? (``os.kill(pid, 0)`` would kill it on Windows.)"""
    if pid <= 0:
        return False
    if not platform.IS_WINDOWS:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    query_limited_information, still_active = 0x1000, 259
    handle = k32.OpenProcess(query_limited_information, False, pid)  # noqa: FBT003
    if not handle:
        return False
    try:
        code = wintypes.DWORD()
        if not k32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == still_active
    finally:
        k32.CloseHandle(handle)


def descendants(pid: int) -> list[int]:
    """Ids of every process below ``pid`` (children, grandchildren, ...). Windows only.

    A job object normally catches these, but PowerShell 7 starts its native children outside
    the job (verified: a ``ping`` launched by ``pwsh`` survives ``TerminateJobObject``, one
    launched by cmd, Python or Windows PowerShell 5.1 does not). Pre-/post-consume scripts
    run under pwsh, so the supervisor walks the tree itself before killing it.
    """
    if not platform.IS_WINDOWS:
        return []
    import ctypes
    from ctypes import wintypes

    class ProcessEntry(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_wchar * 260),
        ]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    k32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    th32cs_snapprocess = 0x2
    snapshot = k32.CreateToolhelp32Snapshot(th32cs_snapprocess, 0)
    if snapshot in (None, wintypes.HANDLE(-1).value):
        return []
    children: dict[int, list[int]] = {}
    try:
        entry = ProcessEntry()
        entry.dwSize = ctypes.sizeof(ProcessEntry)
        more = k32.Process32FirstW(snapshot, ctypes.byref(entry))
        while more:
            children.setdefault(entry.th32ParentProcessID, []).append(
                entry.th32ProcessID,
            )
            more = k32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        k32.CloseHandle(snapshot)
    found: list[int] = []
    queue = [pid]
    while queue:
        for child in children.get(queue.pop(), []):
            if child not in found and child != pid:
                found.append(child)
                queue.append(child)
    return found


def kill_pids(pids: list[int]) -> None:
    """Terminate these processes (Windows). Missing or protected ones are skipped."""
    if not platform.IS_WINDOWS:
        return
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    for pid in pids:
        handle = k32.OpenProcess(_PROCESS_TERMINATE, False, pid)  # noqa: FBT003
        if handle:
            k32.TerminateProcess(handle, 1)
            k32.CloseHandle(handle)


def kill_tree(job: WindowsJob | PosixGroup, pid: int) -> None:
    """Kill ``pid`` and everything below it: the job first, then any process that escaped it."""
    victims = descendants(pid)
    job.terminate()
    kill_pids(victims)
