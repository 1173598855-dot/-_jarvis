"""OS-level Windows AppContainer isolation for trusted child Workers.

Linux isolation is applied by the child after spawn. AppContainer identity
must be applied by the parent at CreateProcessW time, so this module prepares
that identity and the ACL grants it needs.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

WORKER_WINDOWS_ISOLATION = ("appcontainer",)
HRESULT_ALREADY_EXISTS = 0x800700B7
WINERROR_ALREADY_EXISTS = -2147024713


class WorkerWindowsIsolationError(RuntimeError):
    """The declared Windows Worker isolation boundary could not be prepared."""


class WindowsAppContainerIdentity:
    """Parent-owned AppContainer profile, SID and cleanup."""

    def __init__(
        self,
        *,
        name: str,
        sid: Any,
        sid_text: str,
        created: bool,
        api: Any,
    ) -> None:
        self.name = name
        self.sid = sid
        self.sid_text = sid_text
        self.created = created
        self._api = api
        self._closed = False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._api.release_sid(self.sid)
        if self.created:
            self._api.delete_profile(self.name)


class _WindowsAppContainerApi:
    def __init__(self, *, ctypes_module: Any | None = None) -> None:
        if ctypes_module is None:
            try:
                import ctypes as ctypes_module  # noqa: PLC0415
                from ctypes import wintypes as wintypes_module  # noqa: PLC0415
            except ImportError as error:
                raise WorkerWindowsIsolationError(
                    "cannot load the Windows AppContainer interface"
                ) from error
        else:
            wintypes_module = getattr(ctypes_module, "wintypes", ctypes_module)
        self._ctypes = ctypes_module
        self._wintypes = wintypes_module
        try:
            userenv = ctypes_module.WinDLL("userenv", use_last_error=True)
            advapi32 = ctypes_module.WinDLL("advapi32", use_last_error=True)
            kernel32 = ctypes_module.WinDLL("kernel32", use_last_error=True)
        except (AttributeError, OSError) as error:
            raise WorkerWindowsIsolationError(
                "Windows AppContainer APIs are unavailable"
            ) from error
        self._create_profile = userenv.CreateAppContainerProfile
        self._create_profile.argtypes = [
            wintypes_module.LPCWSTR,
            wintypes_module.LPCWSTR,
            wintypes_module.LPCWSTR,
            wintypes_module.LPVOID,
            wintypes_module.DWORD,
            ctypes_module.POINTER(wintypes_module.LPVOID),
        ]
        self._create_profile.restype = ctypes_module.HRESULT
        self._derive_sid = userenv.DeriveAppContainerSidFromAppContainerName
        self._derive_sid.argtypes = [
            wintypes_module.LPCWSTR,
            ctypes_module.POINTER(wintypes_module.LPVOID),
        ]
        self._derive_sid.restype = ctypes_module.HRESULT
        self._delete_profile = userenv.DeleteAppContainerProfile
        self._delete_profile.argtypes = [wintypes_module.LPCWSTR]
        self._delete_profile.restype = ctypes_module.HRESULT
        self._convert_sid = advapi32.ConvertSidToStringSidW
        self._convert_sid.argtypes = [
            wintypes_module.LPVOID,
            ctypes_module.POINTER(wintypes_module.LPWSTR),
        ]
        self._convert_sid.restype = wintypes_module.BOOL
        self._local_free = kernel32.LocalFree
        self._local_free.argtypes = [wintypes_module.HLOCAL]
        self._local_free.restype = wintypes_module.HLOCAL
        self._free_sid = advapi32.FreeSid
        self._free_sid.argtypes = [wintypes_module.LPVOID]
        self._free_sid.restype = wintypes_module.LPVOID

    def create_or_adopt(self, name: str) -> tuple[Any, bool]:
        sid = self._wintypes.LPVOID()
        created = True
        try:
            hr = self._create_profile(
                name, "Jarvis Worker", "Jarvis Worker", None, 0, self._ctypes.byref(sid)
            )
        except OSError as error:
            winerror = int(getattr(error, "winerror", 0) or 0)
            if winerror not in {HRESULT_ALREADY_EXISTS, WINERROR_ALREADY_EXISTS}:
                raise WorkerWindowsIsolationError(
                    "cannot create the Worker AppContainer profile"
                ) from error
            created = False
            hr = 0
        if created and int(hr) != 0:
            if (int(hr) & 0xFFFFFFFF) == HRESULT_ALREADY_EXISTS:
                created = False
            else:
                raise WorkerWindowsIsolationError(
                    f"cannot create the Worker AppContainer profile: HRESULT {int(hr) & 0xFFFFFFFF}"
                )
        if not created:
            hr = self._derive_sid(name, self._ctypes.byref(sid))
            if int(hr) != 0:
                raise WorkerWindowsIsolationError(
                    "cannot derive the Worker AppContainer SID"
                )
        return sid, created

    def sid_text(self, sid: Any) -> str:
        text = self._wintypes.LPWSTR()
        if not self._convert_sid(sid, self._ctypes.byref(text)):
            raise WorkerWindowsIsolationError(
                "cannot convert the Worker AppContainer SID"
            )
        value = str(text.value)
        self._local_free(text)
        if not value:
            raise WorkerWindowsIsolationError(
                "Worker AppContainer SID text was empty"
            )
        return value

    def release_sid(self, sid: Any) -> None:
        try:
            self._free_sid(sid)
        except (OSError, TypeError, ValueError):
            return

    def delete_profile(self, name: str) -> None:
        try:
            self._delete_profile(name)
        except OSError:
            return


ALL_APPLICATION_PACKAGES_SID = "S-1-15-2-1"
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
GENERIC_EXECUTE = 0x20000000
_TRUSTEE_IS_SID = 0
_TRUSTEE_IS_UNKNOWN = 0
_FILE_READ_DATA = 0x0001
_FILE_READ_EA = 0x0008
_FILE_READ_ATTRIBUTES = 0x0080
_FILE_EXECUTE = 0x0020
_READ_CONTROL = 0x00020000
_SYNCHRONIZE = 0x00100000
_FILE_GENERIC_READ = (
    _FILE_READ_DATA
    | _FILE_READ_EA
    | _FILE_READ_ATTRIBUTES
    | _READ_CONTROL
    | _SYNCHRONIZE
)
_GRANT_ACCESS = 1
_SUB_CONTAINERS_AND_OBJECTS_INHERIT = 3
_SE_FILE_OBJECT = 1
_DACL_SECURITY_INFORMATION = 0x00000004


class _WindowsAclApi:
    """Native DACL editing for one parent-owned container SID."""

    def __init__(self, *, ctypes_module: Any | None = None) -> None:
        if ctypes_module is None:
            try:
                import ctypes as ctypes_module  # noqa: PLC0415
                from ctypes import wintypes as wintypes_module  # noqa: PLC0415
            except ImportError as error:
                raise WorkerWindowsIsolationError(
                    "cannot load the Windows ACL interface"
                ) from error
        else:
            wintypes_module = getattr(ctypes_module, "wintypes", ctypes_module)
        self._ctypes = ctypes_module
        self._wintypes = wintypes_module
        try:
            advapi32 = ctypes_module.WinDLL("advapi32", use_last_error=True)
            kernel32 = ctypes_module.WinDLL("kernel32", use_last_error=True)
        except (AttributeError, OSError) as error:
            raise WorkerWindowsIsolationError(
                "Windows ACL APIs are unavailable"
            ) from error

        class TRUSTEE_W(ctypes_module.Structure):
            _fields_ = [
                ("pMultipleTrustee", wintypes_module.LPVOID),
                ("MultipleTrusteeOperation", ctypes_module.c_int),
                ("TrusteeForm", ctypes_module.c_int),
                ("TrusteeType", ctypes_module.c_int),
                ("ptstrName", wintypes_module.LPVOID),
            ]

        class EXPLICIT_ACCESS_W(ctypes_module.Structure):
            _fields_ = [
                ("grfAccessPermissions", wintypes_module.DWORD),
                ("grfAccessMode", ctypes_module.c_int),
                ("grfInheritance", wintypes_module.DWORD),
                ("Trustee", TRUSTEE_W),
            ]

        self._explicit_access = EXPLICIT_ACCESS_W
        self._get_named = advapi32.GetNamedSecurityInfoW
        self._get_named.argtypes = [
            wintypes_module.LPCWSTR,
            ctypes_module.c_int,
            wintypes_module.DWORD,
            ctypes_module.POINTER(wintypes_module.LPVOID),
            ctypes_module.POINTER(wintypes_module.LPVOID),
            ctypes_module.POINTER(wintypes_module.LPVOID),
            ctypes_module.POINTER(wintypes_module.LPVOID),
            ctypes_module.POINTER(wintypes_module.LPVOID),
        ]
        self._get_named.restype = wintypes_module.DWORD
        self._set_entries = advapi32.SetEntriesInAclW
        self._set_entries.argtypes = [
            wintypes_module.ULONG,
            ctypes_module.POINTER(EXPLICIT_ACCESS_W),
            wintypes_module.LPVOID,
            ctypes_module.POINTER(wintypes_module.LPVOID),
        ]
        self._set_entries.restype = wintypes_module.DWORD
        self._set_named = advapi32.SetNamedSecurityInfoW
        self._set_named.argtypes = [
            wintypes_module.LPWSTR,
            ctypes_module.c_int,
            wintypes_module.DWORD,
            wintypes_module.LPVOID,
            wintypes_module.LPVOID,
            wintypes_module.LPVOID,
            wintypes_module.LPVOID,
        ]
        self._set_named.restype = wintypes_module.DWORD
        self._local_free = kernel32.LocalFree
        self._local_free.argtypes = [wintypes_module.HLOCAL]
        self._local_free.restype = wintypes_module.HLOCAL
        self._get_effective_rights = advapi32.GetEffectiveRightsFromAclW
        self._get_effective_rights.argtypes = [
            wintypes_module.LPVOID,
            ctypes_module.POINTER(TRUSTEE_W),
            ctypes_module.POINTER(wintypes_module.DWORD),
        ]
        self._get_effective_rights.restype = wintypes_module.DWORD
        self._string_to_sid = advapi32.ConvertStringSidToSidW
        self._string_to_sid.argtypes = [
            wintypes_module.LPCWSTR,
            ctypes_module.POINTER(wintypes_module.LPVOID),
        ]
        self._string_to_sid.restype = wintypes_module.BOOL
        self._trustee = TRUSTEE_W

    def has_read_execute(self, path: Path, sid_text: str) -> bool:
        """True when the named SID already holds read and execute rights."""
        if not sid_text:
            return False
        existing = self._wintypes.LPVOID()
        descriptor = self._wintypes.LPVOID()
        status = self._get_named(
            str(path),
            _SE_FILE_OBJECT,
            _DACL_SECURITY_INFORMATION,
            None,
            None,
            self._ctypes.byref(existing),
            None,
            self._ctypes.byref(descriptor),
        )
        if int(status) != 0:
            return False
        try:
            if not existing:
                return False
            sid = self._wintypes.LPVOID()
            if not self._string_to_sid(sid_text, self._ctypes.byref(sid)):
                return False
            try:
                trustee = self._trustee()
                trustee.TrusteeForm = _TRUSTEE_IS_SID
                trustee.TrusteeType = _TRUSTEE_IS_UNKNOWN
                trustee.ptstrName = sid
                rights = self._wintypes.DWORD()
                status = self._get_effective_rights(
                    existing, self._ctypes.byref(trustee), self._ctypes.byref(rights)
                )
            finally:
                self._local_free(sid)
            if int(status) != 0:
                return False
            granted = int(rights.value)
            return bool(
                granted & _FILE_GENERIC_READ == _FILE_GENERIC_READ
                and granted & _FILE_EXECUTE
            )
        finally:
            if descriptor:
                self._local_free(descriptor)

    def grant(self, path: Path, sid: Any, access_mask: int) -> None:
        """Add one inheritable grant ACE for the container SID."""
        target = str(path)
        existing = self._wintypes.LPVOID()
        descriptor = self._wintypes.LPVOID()
        status = self._get_named(
            target,
            _SE_FILE_OBJECT,
            _DACL_SECURITY_INFORMATION,
            None,
            None,
            self._ctypes.byref(existing),
            None,
            self._ctypes.byref(descriptor),
        )
        if int(status) != 0:
            raise WorkerWindowsIsolationError(
                f"cannot read the existing DACL for {target}"
            )
        try:
            access = self._explicit_access()
            access.grfAccessPermissions = access_mask
            access.grfAccessMode = _GRANT_ACCESS
            access.grfInheritance = _SUB_CONTAINERS_AND_OBJECTS_INHERIT
            access.Trustee.TrusteeForm = _TRUSTEE_IS_SID
            access.Trustee.TrusteeType = _TRUSTEE_IS_UNKNOWN
            access.Trustee.ptstrName = sid
            updated = self._wintypes.LPVOID()
            status = self._set_entries(
                1,
                self._ctypes.byref(access),
                existing,
                self._ctypes.byref(updated),
            )
            if int(status) != 0:
                raise WorkerWindowsIsolationError(
                    f"cannot build the container DACL for {target}"
                )
            try:
                status = self._set_named(
                    target,
                    _SE_FILE_OBJECT,
                    _DACL_SECURITY_INFORMATION,
                    None,
                    None,
                    updated,
                    None,
                )
                if int(status) != 0:
                    raise WorkerWindowsIsolationError(
                        f"cannot apply the container DACL to {target}"
                    )
            finally:
                self._local_free(updated)
        finally:
            if descriptor:
                self._local_free(descriptor)


def container_read_access_present(
    path: Path,
    *,
    sid_text: str = ALL_APPLICATION_PACKAGES_SID,
    acl_api: Any | None = None,
) -> bool:
    """True when a SID already has read and execute rights on a directory.

    Shared runtime directories are not parent-owned, so the Worker verifies the
    access an AppContainer token already carries instead of rewriting a DACL it
    has no authority over.
    """
    api = _WindowsAclApi() if acl_api is None else acl_api
    return api.has_read_execute(path, sid_text)


def grant_container_paths(
    sid: Any,
    *,
    read_paths: tuple[Path, ...],
    writable_paths: tuple[Path, ...],
    acl_api: Any | None = None,
) -> tuple[tuple[str, str], ...]:
    """Grant a container SID inheritable read and read/write DACL entries.

    Inheritable entries do not reach directory children that already exist, so
    callers grant an empty parent-owned directory before populating it.
    """
    if sid is None:
        raise WorkerWindowsIsolationError("Worker AppContainer SID was empty")
    if not read_paths and not writable_paths:
        raise WorkerWindowsIsolationError("Worker container grants were empty")
    api = _WindowsAclApi() if acl_api is None else acl_api
    applied: list[tuple[str, str]] = []
    requests: tuple[tuple[tuple[Path, ...], int, str], ...] = (
        (read_paths, GENERIC_READ | GENERIC_EXECUTE, "read"),
        (
            writable_paths,
            GENERIC_READ | GENERIC_EXECUTE | GENERIC_WRITE,
            "write",
        ),
    )
    for paths, access_mask, label in requests:
        for path in paths:
            if not path.is_dir():
                raise WorkerWindowsIsolationError(
                    f"Worker container grant target is not a directory: {path}"
                )
            api.grant(path, sid, access_mask)
            applied.append((str(path), label))
    return tuple(applied)


def default_runtime_read_paths(
    *,
    executable: str | None = None,
    base_prefix: str | None = None,
    stdlib_dir: str | None = None,
) -> tuple[Path, ...]:
    """Paths an isolated Python child must be able to read to start."""
    exe = Path(sys.executable if executable is None else executable)
    prefix = Path(sys.base_prefix if base_prefix is None else base_prefix)
    lib = Path(os.path.dirname(os.__file__) if stdlib_dir is None else stdlib_dir)
    paths = (exe.parent, prefix, lib)
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        try:
            resolved = path.resolve()
        except OSError as error:
            raise WorkerWindowsIsolationError(
                "cannot resolve a Worker runtime path"
            ) from error
        if resolved in seen or not resolved.exists():
            continue
        seen.add(resolved)
        unique.append(resolved)
    if not unique:
        raise WorkerWindowsIsolationError("Worker runtime read paths were empty")
    return tuple(unique)


def grant_container_access(
    sid_text: str,
    *,
    read_paths: tuple[Path, ...],
    writable_root: Path,
    runner: Callable[..., Any] | None = None,
) -> tuple[tuple[str, str], ...]:
    """Grant the container SID read runtime paths and one writable Worker root."""
    if not sid_text:
        raise WorkerWindowsIsolationError("Worker AppContainer SID text was empty")
    try:
        writable = writable_root.resolve()
    except OSError as error:
        raise WorkerWindowsIsolationError(
            "cannot resolve the Worker writable root"
        ) from error
    if not writable.is_dir():
        raise WorkerWindowsIsolationError(
            "Worker writable root is not a directory"
        )
    run = subprocess.run if runner is None else runner
    grants: list[tuple[str, str]] = []
    for path in read_paths:
        grants.append((str(path), "(OI)(CI)(GR,GE)"))
    grants.append((str(writable), "(OI)(CI)(M)"))
    for path, rights in grants:
        completed = run(
            ["icacls", path, "/grant", f"*{sid_text}:{rights}"],
            capture_output=True,
            text=True,
            check=False,
        )
        if int(getattr(completed, "returncode", 1)) != 0:
            raise WorkerWindowsIsolationError(
                f"cannot grant Worker AppContainer access to {path}"
            )
    return tuple(grants)


def isolated_python_executable(
    *,
    base_prefix: str | None = None,
) -> Path:
    """Return the base interpreter an AppContainer child can actually start."""
    prefix = Path(sys.base_prefix if base_prefix is None else base_prefix)
    candidate = prefix / "python.exe"
    if not candidate.exists():
        raise WorkerWindowsIsolationError(
            "base Python interpreter is missing for AppContainer launch"
        )
    return candidate


def prepare_windows_worker_isolation(
    writable_root: str | Path,
    *,
    profile_name: str = "jarvis.worker.ac",
    platform_name: str | None = None,
    api_factory: Callable[[], Any] | None = None,
    extra_read_paths: tuple[Path, ...] = (),
    grant: Callable[..., Any] | None = None,
) -> tuple[WindowsAppContainerIdentity, tuple[str, ...]]:
    """Prepare a capability-free AppContainer identity for a Worker child.

    System runtime directories are not granted here. On this host they already
    allow ALL APPLICATION PACKAGES to read/execute, and icacls against them
    fails without elevation. The caller grants only paths it owns.
    """
    platform = sys.platform if platform_name is None else platform_name
    if platform != "win32":
        raise WorkerWindowsIsolationError(
            "Windows AppContainer isolation is unavailable on this platform"
        )
    api = api_factory() if api_factory is not None else _WindowsAppContainerApi()
    identity: WindowsAppContainerIdentity | None = None
    sid: Any = None
    created = False
    try:
        sid, created = api.create_or_adopt(profile_name)
        try:
            sid_text = api.sid_text(sid)
        except Exception:
            try:
                api.release_sid(sid)
            finally:
                if created:
                    api.delete_profile(profile_name)
            raise
        identity = WindowsAppContainerIdentity(
            name=profile_name,
            sid=sid,
            sid_text=sid_text,
            created=created,
            api=api,
        )
        grant_fn = grant_container_access if grant is None else grant
        grant_fn(
            sid_text,
            read_paths=extra_read_paths,
            writable_root=Path(writable_root),
        )
    except Exception:
        if identity is not None:
            identity.close()
        raise
    return identity, WORKER_WINDOWS_ISOLATION



__all__ = [
    "ALL_APPLICATION_PACKAGES_SID",
    "GENERIC_EXECUTE",
    "GENERIC_READ",
    "GENERIC_WRITE",
    "WORKER_WINDOWS_ISOLATION",
    "WindowsAppContainerIdentity",
    "WorkerWindowsIsolationError",
    "container_read_access_present",
    "default_runtime_read_paths",
    "grant_container_access",
    "grant_container_paths",
    "isolated_python_executable",
    "prepare_windows_worker_isolation",
]
