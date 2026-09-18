"""Platform process-tree ownership for trusted Worker launchers."""

from __future__ import annotations

import ctypes
import os
import signal
import subprocess
import time
from ctypes import wintypes
from typing import Any

_POPEN_TYPE = subprocess.Popen
_CREATE_NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200)
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
_JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x8
_JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x100
_JOB_OBJECT_LIMIT_JOB_MEMORY = 0x200
_JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION_CLASS = 1
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9
WORKER_PROCESS_TREE_BUDGETS = {
    "process_memory_bytes": 1024 * 1024 * 1024,
    "job_memory_bytes": 1024 * 1024 * 1024,
    "active_processes": 64,
}
_POSIX_SIGTERM = getattr(signal, "SIGTERM", 15)
_POSIX_SIGKILL = getattr(signal, "SIGKILL", 9)


class ProcessContainmentError(RuntimeError):
    """A Worker process tree could not be placed under parent ownership."""


class _JobObjectBasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class _JobObjectExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JobObjectBasicLimitInformation),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _JobObjectBasicAccountingInformation(ctypes.Structure):
    _fields_ = [
        ("TotalUserTime", ctypes.c_longlong),
        ("TotalKernelTime", ctypes.c_longlong),
        ("ThisPeriodTotalUserTime", ctypes.c_longlong),
        ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
        ("TotalPageFaultCount", wintypes.DWORD),
        ("TotalProcesses", wintypes.DWORD),
        ("ActiveProcesses", wintypes.DWORD),
        ("TotalTerminatedProcesses", wintypes.DWORD),
    ]


class _WindowsJobApi:
    def __init__(self) -> None:
        try:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        except (AttributeError, OSError) as error:
            raise ProcessContainmentError(
                "Windows Job Object APIs are unavailable"
            ) from error
        self._create_job = kernel32.CreateJobObjectW
        self._create_job.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
        self._create_job.restype = wintypes.HANDLE
        self._set_information = kernel32.SetInformationJobObject
        self._set_information.argtypes = (
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        )
        self._set_information.restype = wintypes.BOOL
        self._assign_process = kernel32.AssignProcessToJobObject
        self._assign_process.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
        self._assign_process.restype = wintypes.BOOL
        self._terminate_job = kernel32.TerminateJobObject
        self._terminate_job.argtypes = (wintypes.HANDLE, wintypes.UINT)
        self._terminate_job.restype = wintypes.BOOL
        self._query_information = kernel32.QueryInformationJobObject
        self._query_information.argtypes = (
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        )
        self._query_information.restype = wintypes.BOOL
        self._close_handle = kernel32.CloseHandle
        self._close_handle.argtypes = (wintypes.HANDLE,)
        self._close_handle.restype = wintypes.BOOL

    @staticmethod
    def _raise(operation: str) -> None:
        code = ctypes.get_last_error()
        raise ProcessContainmentError(
            f"Windows Job Object {operation} failed with error {code}"
        )

    def create(self) -> int:
        handle = self._create_job(None, None)
        if not handle:
            self._raise("creation")
        value = int(handle)
        limits = _JobObjectExtendedLimitInformation()
        limits.BasicLimitInformation.LimitFlags = (
            _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            | _JOB_OBJECT_LIMIT_ACTIVE_PROCESS
            | _JOB_OBJECT_LIMIT_PROCESS_MEMORY
            | _JOB_OBJECT_LIMIT_JOB_MEMORY
        )
        limits.BasicLimitInformation.ActiveProcessLimit = (
            WORKER_PROCESS_TREE_BUDGETS["active_processes"]
        )
        limits.ProcessMemoryLimit = WORKER_PROCESS_TREE_BUDGETS[
            "process_memory_bytes"
        ]
        limits.JobMemoryLimit = WORKER_PROCESS_TREE_BUDGETS["job_memory_bytes"]
        if not self._set_information(
            value,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
            ctypes.byref(limits),
            ctypes.sizeof(limits),
        ):
            self._close_handle(value)
            self._raise("configuration")
        return value

    def assign(self, job_handle: int, process_handle: int) -> None:
        if not self._assign_process(job_handle, process_handle):
            self._raise("assignment")

    def terminate(self, job_handle: int, force: bool) -> bool:
        exit_code = 137 if force else 143
        return bool(self._terminate_job(job_handle, exit_code))

    def active_processes(self, job_handle: int) -> int:
        accounting = _JobObjectBasicAccountingInformation()
        returned = wintypes.DWORD()
        if not self._query_information(
            job_handle,
            _JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION_CLASS,
            ctypes.byref(accounting),
            ctypes.sizeof(accounting),
            ctypes.byref(returned),
        ):
            self._raise("query")
        return int(accounting.ActiveProcesses)

    def close(self, job_handle: int) -> bool:
        return bool(self._close_handle(job_handle))


def process_group_popen_kwargs() -> dict[str, Any]:
    """Return launch flags that put a real Worker in its own process group."""
    if os.name == "nt":
        return {"creationflags": _CREATE_NEW_PROCESS_GROUP}
    if os.name == "posix":
        return {"start_new_session": True}
    return {}


class ProcessTreeContainment:
    """Own the process group or Windows Job for one real Worker Popen."""

    def __init__(
        self,
        process: subprocess.Popen[Any],
        *,
        process_group_id: int | None = None,
        job_api: _WindowsJobApi | None = None,
        job_handle: int | None = None,
    ) -> None:
        self._process = process
        self._process_group_id = process_group_id
        self._job_api = job_api
        self._job_handle = job_handle
        self._closed = False

    @classmethod
    def attach(
        cls,
        process: subprocess.Popen[Any],
    ) -> ProcessTreeContainment | None:
        """Attach a real Popen; test doubles retain direct-process semantics."""
        if not isinstance(process, _POPEN_TYPE):
            return None
        if os.name == "posix":
            try:
                process_group_id = os.getpgid(process.pid)
            except OSError as error:
                raise ProcessContainmentError(
                    "Worker process group could not be inspected"
                ) from error
            if process_group_id != process.pid:
                raise ProcessContainmentError(
                    "Worker process is not the leader of its process group"
                )
            return cls(process, process_group_id=process_group_id)
        if os.name == "nt":
            raw_process_handle = getattr(process, "_handle", None)
            if raw_process_handle is None:
                raise ProcessContainmentError(
                    "Worker process handle is unavailable"
                )
            api = _WindowsJobApi()
            job_handle = api.create()
            try:
                api.assign(job_handle, int(raw_process_handle))
            except BaseException:
                api.close(job_handle)
                raise
            return cls(process, job_api=api, job_handle=job_handle)
        raise ProcessContainmentError("Worker process containment is unsupported")

    @property
    def is_attached(self) -> bool:
        return not self._closed and (
            self._process_group_id is not None or self._job_handle is not None
        )

    def terminate(self, *, force: bool) -> bool:
        if self._closed:
            return True
        if self._process_group_id is not None:
            try:
                os.killpg(
                    self._process_group_id,
                    _POSIX_SIGKILL if force else _POSIX_SIGTERM,
                )
                return True
            except ProcessLookupError:
                return True
            except OSError:
                return False
        if self._job_api is not None and self._job_handle is not None:
            return self._job_api.terminate(self._job_handle, force)
        return False

    def wait_empty(self, timeout: float) -> bool:
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            if self._process_group_id is not None:
                try:
                    os.killpg(self._process_group_id, 0)
                except ProcessLookupError:
                    return True
                except OSError:
                    return False
            elif self._job_api is not None and self._job_handle is not None:
                try:
                    if self._job_api.active_processes(self._job_handle) == 0:
                        return True
                except ProcessContainmentError:
                    return False
            else:
                return False
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(0.01, remaining))

    def close(self) -> bool:
        if self._closed:
            return True
        # Keep ownership until the process tree has been independently
        # observed empty; closing a Windows Job handle can otherwise trigger
        # kill-on-close while descendants are still active.
        if not self.wait_empty(0):
            return False
        if self._job_api is not None and self._job_handle is not None:
            if not self._job_api.close(self._job_handle):
                return False
            self._job_handle = None
        self._closed = True
        return True


__all__ = [
    "WORKER_PROCESS_TREE_BUDGETS",
    "ProcessContainmentError",
    "ProcessTreeContainment",
    "process_group_popen_kwargs",
]
