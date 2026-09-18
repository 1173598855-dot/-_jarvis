"""Parent-owned Windows AppContainer transport for one trusted Worker child.

Linux Workers tighten themselves after fork/exec. Windows AppContainer identity
must be applied by the parent at `CreateProcessW` time, so this module owns the
container identity, the read-only code snapshot the child executes, the single
writable root and the spawn itself.

The child only ever sees a parent-owned snapshot: the repository stays outside
the container's read set, so a compromised Worker cannot read or rewrite the
sources it was started from.
"""

from __future__ import annotations

import ctypes
import itertools
import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Any, Callable, Sequence

from core.kernel.worker_staging import (
    WORKER_STAGE_ENTRY_BUDGET,
    WorkerStagingError,
    stage_worker_tree,
)
from core.kernel.worker_windows_isolation import (
    WindowsAppContainerIdentity,
    WorkerWindowsIsolationError,
    container_read_access_present,
    grant_container_paths,
    isolated_python_executable,
    prepare_windows_worker_isolation,
)

WORKER_WINDOWS_CONTAINER = ("appcontainer", "staged-readonly-code", "writable-root")
CONTAINER_STAGE_ENTRY_BUDGET = WORKER_STAGE_ENTRY_BUDGET
_CONTAINER_REQUIRED_ENVIRONMENT = ("LOCALAPPDATA",)
_PROFILE_SEQUENCE = itertools.count(1)
_PROFILE_LOCK = threading.Lock()

_EXTENDED_STARTUPINFO_PRESENT = 0x00080000
_CREATE_UNICODE_ENVIRONMENT = 0x00000400
_CREATE_SUSPENDED = 0x00000004
_PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES = 0x00020009
_PROC_THREAD_ATTRIBUTE_HANDLE_LIST = 0x00020002
_STARTF_USESTDHANDLES = 0x00000100
_INVALID_HANDLE = -1


class WorkerContainerError(RuntimeError):
    """The parent-owned Windows Worker container could not be established."""


def container_profile_name() -> str:
    """One process-unique AppContainer profile name inside the 64-char limit."""
    with _PROFILE_LOCK:
        sequence = next(_PROFILE_SEQUENCE)
    return f"jarvis.worker.{os.getpid()}.{sequence}"


def container_environment(base: dict[str, str]) -> dict[str, str]:
    """Add the variables an AppContainer child needs to start at all.

    `CreateProcessW` fails with ERROR_ENVVAR_NOT_FOUND when an explicit
    environment block omits the container's own local application data root.
    """
    environment = dict(base)
    by_casefold = {key.casefold(): value for key, value in os.environ.items()}
    for name in _CONTAINER_REQUIRED_ENVIRONMENT:
        if name in environment:
            continue
        value = by_casefold.get(name.casefold())
        if value is None:
            raise WorkerContainerError(
                f"the Worker container requires the {name} environment variable"
            )
        environment[name] = value
    return environment


def stage_container_tree(
    source: Path,
    destination: Path,
    *,
    entry_budget: int = CONTAINER_STAGE_ENTRY_BUDGET,
    copy_tree: Callable[..., Any] | None = None,
) -> int:
    """Compatibility wrapper around the shared bounded staging primitive."""
    try:
        return stage_worker_tree(
            source,
            destination,
            entry_budget=entry_budget,
            copy_tree=copy_tree,
        )
    except WorkerStagingError as error:
        raise WorkerContainerError(str(error)) from error


class WindowsWorkerContainer:
    """One container generation: identity, staged code, writable root, spawn."""

    def __init__(
        self,
        *,
        identity: WindowsAppContainerIdentity,
        root: Path,
        code_root: Path,
        writable_root: Path,
        interpreter: Path,
    ) -> None:
        self.identity = identity
        self.root = root
        self.code_root = code_root
        self.writable_root = writable_root
        self.interpreter = interpreter
        self.labels = WORKER_WINDOWS_CONTAINER
        self._closed = False
        self._resume_thread_handle: int | None = None

    @classmethod
    def create(
        cls,
        *,
        profile_name: str | None = None,
        prepare: Callable[..., Any] | None = None,
        grant: Callable[..., Any] | None = None,
        interpreter: Path | None = None,
        temporary_directory: Callable[..., str] | None = None,
        verify_interpreter: Callable[[Path], bool] | None = None,
    ) -> WindowsWorkerContainer:
        """Create a capability-free container with an empty granted stage."""
        make_temporary = tempfile.mkdtemp if temporary_directory is None else temporary_directory
        try:
            root = Path(make_temporary(prefix="jarvis-worker-container-"))
        except OSError as error:
            raise WorkerContainerError(
                "cannot create the Worker container root"
            ) from error
        identity: WindowsAppContainerIdentity | None = None
        try:
            code_root = root / "code"
            writable_root = root / "tmp"
            code_root.mkdir()
            writable_root.mkdir()
            resolved_interpreter = (
                isolated_python_executable() if interpreter is None else Path(interpreter)
            )
            verify = (
                _interpreter_is_container_readable
                if verify_interpreter is None
                else verify_interpreter
            )
            if not verify(resolved_interpreter):
                raise WorkerContainerError(
                    "the Worker interpreter is not readable by an AppContainer: "
                    f"{resolved_interpreter}"
                )
            prepare_fn = (
                prepare_windows_worker_isolation if prepare is None else prepare
            )
            identity = prepare_fn(
                writable_root,
                profile_name=profile_name or container_profile_name(),
                grant=lambda *arguments, **keywords: (),
            )[0]
            grant_fn = grant_container_paths if grant is None else grant
            grant_fn(
                identity.sid,
                read_paths=(code_root,),
                writable_paths=(writable_root,),
            )
        except WorkerWindowsIsolationError as error:
            if identity is not None:
                identity.close()
            _remove_container_root(root)
            raise WorkerContainerError(
                "cannot prepare the Worker container identity"
            ) from error
        except BaseException:
            if identity is not None:
                identity.close()
            _remove_container_root(root)
            raise
        return cls(
            identity=identity,
            root=root,
            code_root=code_root,
            writable_root=writable_root,
            interpreter=resolved_interpreter,
        )

    def stage(self, source: Path, name: str) -> Path:
        """Stage one tree under the granted read-only code root."""
        if self._closed:
            raise WorkerContainerError("the Worker container is already closed")
        if not name or name in {".", ".."} or Path(name).parts != (name,):
            raise WorkerContainerError("Worker container stage name is invalid")
        destination = self.code_root / name
        if destination.exists():
            raise WorkerContainerError(
                f"Worker container stage target already exists: {name}"
            )
        stage_container_tree(source, destination)
        return destination

    def spawn(
        self,
        arguments: Sequence[str],
        *,
        cwd: Path,
        environment: dict[str, str],
        popen: Callable[..., Any] | None = None,
        **launch_keywords: Any,
    ) -> Any:
        """Start the child with this container's identity and standard pipes."""
        if self._closed:
            raise WorkerContainerError("the Worker container is already closed")
        factory = AppContainerPopen if popen is None else popen
        return factory(
            list(arguments),
            cwd=str(cwd),
            env=container_environment(environment),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            bufsize=0,
            close_fds=True,
            app_container_sid=self.identity.sid,
            **launch_keywords,
        )

    def close(self) -> None:
        """Release the identity, delete the profile and remove the stage."""
        if self._closed:
            return
        self._closed = True
        try:
            self.identity.close()
        finally:
            _remove_container_root(self.root)

    def close_spawn_handle(self) -> None:
        """Compatibility hook for a factory that owns the spawn handle."""
        return None


def _interpreter_is_container_readable(interpreter: Path) -> bool:
    """True when every AppContainer token can already read the interpreter.

    The interpreter tree is shared and not parent-owned, so the container never
    rewrites its DACL: a standard Python installation already grants
    ALL APPLICATION PACKAGES read and execute, and anything else fails closed.
    """
    return container_read_access_present(interpreter.parent)


def _remove_container_root(root: Path) -> None:
    """Best-effort removal; a retained stage must never mask a Worker result."""
    shutil.rmtree(root, ignore_errors=True)


class _ContainerSpawnApi:
    """Minimal `CreateProcessW` surface that carries container identity."""

    def __init__(self, *, ctypes_module: Any | None = None) -> None:
        if ctypes_module is None:
            try:
                import ctypes as ctypes_module  # noqa: PLC0415
                from ctypes import wintypes as wintypes_module  # noqa: PLC0415
            except ImportError as error:
                raise WorkerContainerError(
                    "cannot load the Windows process creation interface"
                ) from error
        else:
            wintypes_module = getattr(ctypes_module, "wintypes", ctypes_module)
        self._ctypes = ctypes_module
        self._wintypes = wintypes_module
        try:
            kernel32 = ctypes_module.WinDLL("kernel32", use_last_error=True)
        except (AttributeError, OSError) as error:
            raise WorkerContainerError(
                "Windows process creation APIs are unavailable"
            ) from error
        self._kernel32 = kernel32

        class STARTUPINFOW(ctypes_module.Structure):
            _fields_ = [
                ("cb", wintypes_module.DWORD),
                ("lpReserved", wintypes_module.LPWSTR),
                ("lpDesktop", wintypes_module.LPWSTR),
                ("lpTitle", wintypes_module.LPWSTR),
                ("dwX", wintypes_module.DWORD),
                ("dwY", wintypes_module.DWORD),
                ("dwXSize", wintypes_module.DWORD),
                ("dwYSize", wintypes_module.DWORD),
                ("dwXCountChars", wintypes_module.DWORD),
                ("dwYCountChars", wintypes_module.DWORD),
                ("dwFillAttribute", wintypes_module.DWORD),
                ("dwFlags", wintypes_module.DWORD),
                ("wShowWindow", wintypes_module.WORD),
                ("cbReserved2", wintypes_module.WORD),
                ("lpReserved2", ctypes_module.POINTER(ctypes_module.c_byte)),
                ("hStdInput", wintypes_module.HANDLE),
                ("hStdOutput", wintypes_module.HANDLE),
                ("hStdError", wintypes_module.HANDLE),
            ]

        class STARTUPINFOEXW(ctypes_module.Structure):
            _fields_ = [
                ("StartupInfo", STARTUPINFOW),
                ("lpAttributeList", wintypes_module.LPVOID),
            ]

        class PROCESS_INFORMATION(ctypes_module.Structure):
            _fields_ = [
                ("hProcess", wintypes_module.HANDLE),
                ("hThread", wintypes_module.HANDLE),
                ("dwProcessId", wintypes_module.DWORD),
                ("dwThreadId", wintypes_module.DWORD),
            ]

        class SECURITY_CAPABILITIES(ctypes_module.Structure):
            _fields_ = [
                ("AppContainerSid", wintypes_module.LPVOID),
                ("Capabilities", wintypes_module.LPVOID),
                ("CapabilityCount", wintypes_module.DWORD),
                ("Reserved", wintypes_module.DWORD),
            ]

        self._startupinfoex = STARTUPINFOEXW
        self._process_information = PROCESS_INFORMATION
        self._security_capabilities = SECURITY_CAPABILITIES
        kernel32.CreateProcessW.argtypes = [
            wintypes_module.LPCWSTR,
            wintypes_module.LPWSTR,
            wintypes_module.LPVOID,
            wintypes_module.LPVOID,
            wintypes_module.BOOL,
            wintypes_module.DWORD,
            wintypes_module.LPVOID,
            wintypes_module.LPCWSTR,
            ctypes_module.POINTER(STARTUPINFOEXW),
            ctypes_module.POINTER(PROCESS_INFORMATION),
        ]
        kernel32.CreateProcessW.restype = wintypes_module.BOOL

    def create(
        self,
        *,
        command_line: str,
        cwd: str | None,
        environment: dict[str, str] | None,
        creation_flags: int,
        standard_handles: tuple[int, int, int],
        app_container_sid: Any,
    ) -> tuple[int, int, int, int]:
        """Create one contained child and return its process handle and ids."""
        ctypes_module = self._ctypes
        wintypes_module = self._wintypes
        kernel32 = self._kernel32
        size = ctypes_module.c_size_t()
        kernel32.InitializeProcThreadAttributeList(
            None, 2, 0, ctypes_module.byref(size)
        )
        if int(size.value) <= 0:
            raise WorkerContainerError(
                "cannot size the Worker container attribute list"
            )
        buffer = (ctypes_module.c_byte * size.value)()
        if not kernel32.InitializeProcThreadAttributeList(
            buffer, 2, 0, ctypes_module.byref(size)
        ):
            raise WorkerContainerError(
                "cannot initialize the Worker container attribute list"
            )
        try:
            capabilities = self._security_capabilities()
            capabilities.AppContainerSid = app_container_sid
            if not kernel32.UpdateProcThreadAttribute(
                buffer,
                0,
                _PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES,
                ctypes_module.byref(capabilities),
                ctypes_module.sizeof(capabilities),
                None,
                None,
            ):
                raise WorkerContainerError(
                    "cannot apply the Worker container identity"
                )
            handle_array = (wintypes_module.HANDLE * len(standard_handles))(
                *[wintypes_module.HANDLE(handle) for handle in standard_handles]
            )
            if not kernel32.UpdateProcThreadAttribute(
                buffer,
                0,
                _PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
                ctypes_module.byref(handle_array),
                ctypes_module.sizeof(handle_array),
                None,
                None,
            ):
                raise WorkerContainerError(
                    "cannot restrict the Worker container handle list"
                )
            startup = self._startupinfoex()
            startup.StartupInfo.cb = ctypes_module.sizeof(self._startupinfoex)
            startup.StartupInfo.dwFlags = _STARTF_USESTDHANDLES
            startup.StartupInfo.hStdInput = wintypes_module.HANDLE(standard_handles[0])
            startup.StartupInfo.hStdOutput = wintypes_module.HANDLE(standard_handles[1])
            startup.StartupInfo.hStdError = wintypes_module.HANDLE(standard_handles[2])
            startup.lpAttributeList = ctypes_module.cast(
                buffer, wintypes_module.LPVOID
            )
            block = None
            if environment is not None:
                joined = "".join(
                    f"{key}={value}\0" for key, value in environment.items()
                )
                block = ctypes_module.create_unicode_buffer(joined + "\0")
            information = self._process_information()
            flags = (
                int(creation_flags)
                | _EXTENDED_STARTUPINFO_PRESENT
                | _CREATE_UNICODE_ENVIRONMENT
                | _CREATE_SUSPENDED
            )
            created = kernel32.CreateProcessW(
                None,
                ctypes_module.create_unicode_buffer(command_line),
                None,
                None,
                True,
                flags,
                (
                    ctypes_module.cast(block, wintypes_module.LPVOID)
                    if block is not None
                    else None
                ),
                cwd,
                ctypes_module.byref(startup),
                ctypes_module.byref(information),
            )
            if not created:
                raise OSError(
                    ctypes_module.get_last_error(),
                    "the contained Worker process could not be created",
                )
            return (
                int(information.hProcess),
                int(information.dwProcessId),
                int(information.dwThreadId),
                int(information.hThread),
            )
        finally:
            kernel32.DeleteProcThreadAttributeList(buffer)


class AppContainerPopen(subprocess.Popen):
    """A `Popen` whose child carries a parent-owned AppContainer identity.

    Standard `subprocess` only exposes `handle_list` inside its attribute list,
    so security capabilities require replacing the Windows spawn while keeping
    every other `Popen` behaviour, including the pipes, process handle and the
    `ProcessTreeContainment` Job Object attachment, unchanged.
    """

    def __init__(
        self,
        *arguments: Any,
        app_container_sid: Any = None,
        spawn_api: Any | None = None,
        **keywords: Any,
    ) -> None:
        if app_container_sid is None:
            raise WorkerContainerError(
                "a contained Worker requires an AppContainer SID"
            )
        self._app_container_sid = app_container_sid
        self._spawn_api = spawn_api
        self._resume_thread_handle: int | None = None
        super().__init__(*arguments, **keywords)

    def _execute_child(  # type: ignore[override]
        self,
        args: Any,
        executable: Any,
        preexec_fn: Any,
        close_fds: Any,
        pass_fds: Any,
        cwd: Any,
        env: Any,
        startupinfo: Any,
        creationflags: Any,
        shell: Any,
        p2cread: Any,
        p2cwrite: Any,
        c2pread: Any,
        c2pwrite: Any,
        errread: Any,
        errwrite: Any,
        *unused_arguments: Any,
        **unused_keywords: Any,
    ) -> None:
        if shell or pass_fds:
            raise WorkerContainerError(
                "a contained Worker cannot use a shell or extra descriptors"
            )
        if _INVALID_HANDLE in (int(p2cread), int(c2pwrite), int(errwrite)):
            raise WorkerContainerError(
                "a contained Worker requires all three standard pipes"
            )
        command_line = (
            args if isinstance(args, str) else subprocess.list2cmdline(args)
        )
        api = _ContainerSpawnApi() if self._spawn_api is None else self._spawn_api
        thread_handle: int | None = None
        try:
            process_handle, pid, _thread_id, thread_handle = api.create(
                command_line=command_line,
                cwd=None if cwd is None else os.fsdecode(cwd),
                environment=None if env is None else dict(env),
                creation_flags=int(creationflags),
                standard_handles=(int(p2cread), int(c2pwrite), int(errwrite)),
                app_container_sid=self._app_container_sid,
            )
        finally:
            self._close_pipe_fds(
                p2cread, p2cwrite, c2pread, c2pwrite, errread, errwrite
            )
        self._child_created = True
        self._handle = subprocess.Handle(process_handle)
        self.pid = pid
        self._resume_thread_handle = thread_handle

    def resume(self) -> None:
        """Resume only after the parent has attached process containment."""
        thread_handle = self._resume_thread_handle
        if thread_handle is None:
            return
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        if kernel32.ResumeThread(thread_handle) == 0xFFFFFFFF:
            raise WorkerContainerError(
                "the contained Worker thread could not resume"
            )
        kernel32.CloseHandle(thread_handle)
        self._resume_thread_handle = None

    def close_spawn_handle(self) -> None:
        """Close the suspended thread handle after failed setup or exit."""
        thread_handle = self._resume_thread_handle
        if thread_handle is None:
            return
        ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(thread_handle)
        self._resume_thread_handle = None


__all__ = [
    "CONTAINER_STAGE_ENTRY_BUDGET",
    "WORKER_WINDOWS_CONTAINER",
    "AppContainerPopen",
    "WindowsWorkerContainer",
    "WorkerContainerError",
    "container_environment",
    "container_profile_name",
    "stage_container_tree",
]
