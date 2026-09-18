"""Windows AppContainer Worker isolation tests."""

from __future__ import annotations

import ast
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from core.kernel.worker_windows_isolation import (
    WORKER_WINDOWS_ISOLATION,
    WindowsAppContainerIdentity,
    WorkerWindowsIsolationError,
    default_runtime_read_paths,
    grant_container_access,
    prepare_windows_worker_isolation,
)


class _FakeCompleted:
    def __init__(self, returncode: int = 0) -> None:
        self.returncode = returncode
        self.stdout = ""
        self.stderr = ""


class _FakeApi:
    def __init__(
        self,
        *,
        created: bool = True,
        fail_at: str | None = None,
        sid_text: str = "S-1-15-2-1",
    ) -> None:
        self.created = created
        self.fail_at = fail_at
        self._sid_text = sid_text
        self.released = False
        self.deleted: list[str] = []
        self.sid = object()

    def create_or_adopt(self, name: str) -> tuple[object, bool]:
        if self.fail_at == "create":
            raise WorkerWindowsIsolationError("create failed")
        return self.sid, self.created

    def sid_text(self, sid: object) -> str:
        if self.fail_at == "sid":
            raise WorkerWindowsIsolationError("sid failed")
        return self._sid_text

    def release_sid(self, sid: object) -> None:
        self.released = True

    def delete_profile(self, name: str) -> None:
        self.deleted.append(name)


class TestWindowsIsolationContract(unittest.TestCase):
    def test_declares_a_single_fixed_windows_boundary(self) -> None:
        self.assertEqual(WORKER_WINDOWS_ISOLATION, ("appcontainer",))

    def test_non_windows_platforms_fail_closed(self) -> None:
        with self.assertRaises(WorkerWindowsIsolationError):
            prepare_windows_worker_isolation(
                Path(tempfile.gettempdir()),
                platform_name="linux",
                api_factory=lambda: _FakeApi(),
            )

    def test_existing_profile_is_adopted_not_fatal(self) -> None:
        api = _FakeApi(created=False)
        with tempfile.TemporaryDirectory() as tmp:
            identity, labels = prepare_windows_worker_isolation(
                Path(tmp),
                platform_name="win32",
                api_factory=lambda: api,
                extra_read_paths=(Path(tmp),),
                grant=lambda *arguments, **kwargs: (("ok", "(M)"),),
            )
        self.assertFalse(identity.created)
        self.assertEqual(labels, WORKER_WINDOWS_ISOLATION)
        identity.close()
        self.assertEqual(api.deleted, [])
        self.assertTrue(api.released)

    def test_created_profile_is_deleted_on_close(self) -> None:
        api = _FakeApi(created=True)
        with tempfile.TemporaryDirectory() as tmp:
            identity, _labels = prepare_windows_worker_isolation(
                Path(tmp),
                profile_name="jarvis.test.ac",
                platform_name="win32",
                api_factory=lambda: api,
                extra_read_paths=(Path(tmp),),
                grant=lambda *arguments, **kwargs: (("ok", "(M)"),),
            )
        identity.close()
        identity.close()
        self.assertEqual(api.deleted, ["jarvis.test.ac"])

    def test_create_failure_fails_closed_without_identity(self) -> None:
        with self.assertRaises(WorkerWindowsIsolationError):
            prepare_windows_worker_isolation(
                Path(tempfile.gettempdir()),
                platform_name="win32",
                api_factory=lambda: _FakeApi(fail_at="create"),
            )

    def test_sid_failure_fails_closed(self) -> None:
        with self.assertRaises(WorkerWindowsIsolationError):
            prepare_windows_worker_isolation(
                Path(tempfile.gettempdir()),
                platform_name="win32",
                api_factory=lambda: _FakeApi(fail_at="sid"),
            )

    def test_sid_failure_releases_sid_and_created_profile(self) -> None:
        api = _FakeApi(created=True, fail_at="sid")
        with self.assertRaises(WorkerWindowsIsolationError):
            prepare_windows_worker_isolation(
                Path(tempfile.gettempdir()),
                profile_name="jarvis.sid-failure.ac",
                platform_name="win32",
                api_factory=lambda: api,
            )
        self.assertTrue(api.released)
        self.assertEqual(api.deleted, ["jarvis.sid-failure.ac"])

    def test_empty_sid_text_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(WorkerWindowsIsolationError):
                grant_container_access(
                    "",
                    read_paths=(Path(tmp),),
                    writable_root=Path(tmp),
                    runner=lambda *arguments, **kwargs: _FakeCompleted(),
                )

    def test_grant_failure_closes_created_profile(self) -> None:
        api = _FakeApi(created=True)

        def failing_grant(*arguments, **kwargs):
            raise WorkerWindowsIsolationError("grant failed")

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(WorkerWindowsIsolationError):
                prepare_windows_worker_isolation(
                    Path(tmp),
                    profile_name="jarvis.fail.ac",
                    platform_name="win32",
                    api_factory=lambda: api,
                    extra_read_paths=(Path(tmp),),
                    grant=failing_grant,
                )
        self.assertEqual(api.deleted, ["jarvis.fail.ac"])
        self.assertTrue(api.released)

    def test_writable_grant_is_last_and_distinct(self) -> None:
        commands: list[list[str]] = []

        def runner(command, **kwargs):
            commands.append(list(command))
            return _FakeCompleted()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            read_dir = root / "read"
            write_dir = root / "write"
            read_dir.mkdir()
            write_dir.mkdir()
            grants = grant_container_access(
                "S-1-15-2-9",
                read_paths=(read_dir,),
                writable_root=write_dir,
                runner=runner,
            )

        self.assertEqual(grants[-1][1], "(OI)(CI)(M)")
        self.assertEqual(commands[-1][3], "*S-1-15-2-9:(OI)(CI)(M)")
        self.assertTrue(all("(GR,GE)" in command[3] for command in commands[:-1]))

    def test_runtime_paths_prefer_base_interpreter_prefix(self) -> None:
        paths = default_runtime_read_paths()
        self.assertIn(Path(sys.base_prefix).resolve(), paths)
        self.assertTrue(all(path.exists() for path in paths))

    def test_identity_close_is_safe_without_created_profile(self) -> None:
        api = _FakeApi(created=False)
        identity = WindowsAppContainerIdentity(
            name="adopted",
            sid=object(),
            sid_text="S-1-15-2-1",
            created=False,
            api=api,
        )
        identity.close()
        self.assertEqual(api.deleted, [])
        self.assertTrue(api.released)


@unittest.skipUnless(sys.platform == "win32", "Windows AppContainer enforcement")
class TestWindowsIsolationRealEnforcement(unittest.TestCase):
    def test_container_denies_outside_read_and_network_but_allows_granted_write(self) -> None:
        result = _run_enforcement(isolate=True)
        self.assertEqual(result["exit"], 0, result)
        payload = result["payload"]
        self.assertIn("read_err", payload)
        self.assertEqual(int(payload["read_err"]), 13)
        self.assertEqual(payload.get("write"), "ok")
        self.assertNotEqual(payload.get("net"), "ok", payload)
        self.assertTrue(
            payload.get("net_err") is not None
            or payload.get("net_winerror") is not None
            or payload.get("net_exc"),
            payload,
        )

    def test_same_child_without_container_still_reads_and_connects(self) -> None:
        result = _run_enforcement(isolate=False)
        self.assertEqual(result["exit"], 0, result)
        payload = result["payload"]
        self.assertEqual(payload.get("read"), "classified")
        self.assertEqual(payload.get("write"), "ok")
        self.assertEqual(payload.get("net"), "ok")


def _run_enforcement(*, isolate: bool) -> dict:
    import ctypes
    import msvcrt
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES = 0x00020009
    EXTENDED_STARTUPINFO_PRESENT = 0x00080000
    CREATE_UNICODE_ENVIRONMENT = 0x00000400
    CREATE_NEW_PROCESS_GROUP = 0x00000200
    STARTF_USESTDHANDLES = 0x00000100
    HANDLE_FLAG_INHERIT = 0x00000001

    class SECURITY_CAPABILITIES(ctypes.Structure):
        _fields_ = [
            ("AppContainerSid", wintypes.LPVOID),
            ("Capabilities", wintypes.LPVOID),
            ("CapabilityCount", wintypes.DWORD),
            ("Reserved", wintypes.DWORD),
        ]

    class STARTUPINFOW(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("lpReserved", wintypes.LPWSTR),
            ("lpDesktop", wintypes.LPWSTR),
            ("lpTitle", wintypes.LPWSTR),
            ("dwX", wintypes.DWORD),
            ("dwY", wintypes.DWORD),
            ("dwXSize", wintypes.DWORD),
            ("dwYSize", wintypes.DWORD),
            ("dwXCountChars", wintypes.DWORD),
            ("dwYCountChars", wintypes.DWORD),
            ("dwFillAttribute", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("wShowWindow", wintypes.WORD),
            ("cbReserved2", wintypes.WORD),
            ("lpReserved2", ctypes.POINTER(wintypes.BYTE)),
            ("hStdInput", wintypes.HANDLE),
            ("hStdOutput", wintypes.HANDLE),
            ("hStdError", wintypes.HANDLE),
        ]

    class STARTUPINFOEXW(ctypes.Structure):
        _fields_ = [
            ("StartupInfo", STARTUPINFOW),
            ("lpAttributeList", wintypes.LPVOID),
        ]

    class PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("hProcess", wintypes.HANDLE),
            ("hThread", wintypes.HANDLE),
            ("dwProcessId", wintypes.DWORD),
            ("dwThreadId", wintypes.DWORD),
        ]

    SIZE_T = ctypes.c_size_t
    kernel32.InitializeProcThreadAttributeList.argtypes = [
        wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(SIZE_T)
    ]
    kernel32.InitializeProcThreadAttributeList.restype = wintypes.BOOL
    kernel32.UpdateProcThreadAttribute.argtypes = [
        wintypes.LPVOID, wintypes.DWORD, ctypes.c_void_p, wintypes.LPVOID,
        SIZE_T, wintypes.LPVOID, ctypes.POINTER(SIZE_T),
    ]
    kernel32.UpdateProcThreadAttribute.restype = wintypes.BOOL
    kernel32.DeleteProcThreadAttributeList.argtypes = [wintypes.LPVOID]
    kernel32.CreateProcessW.argtypes = [
        wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.LPVOID, wintypes.LPVOID,
        wintypes.BOOL, wintypes.DWORD, wintypes.LPVOID, wintypes.LPCWSTR,
        ctypes.POINTER(STARTUPINFOEXW), ctypes.POINTER(PROCESS_INFORMATION),
    ]
    kernel32.CreateProcessW.restype = wintypes.BOOL
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.SetHandleInformation.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD]
    kernel32.SetHandleInformation.restype = wintypes.BOOL

    root = Path(tempfile.mkdtemp(prefix="jarvis-ac-test-"))
    writable = root / "writable"
    writable.mkdir()
    secret = root / "secret.txt"
    secret.write_text("classified", encoding="utf-8")
    log_path = writable / "child.log"
    child_py = writable / "child.py"
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = int(listener.getsockname()[1])
    result_path = writable / "result.txt"
    child_py.write_text(
        "import os, socket\n"
        f"secret = {str(secret)!r}\n"
        f"writable = {str(writable)!r}\n"
        f"result_path = {str(result_path)!r}\n"
        f"port = {port}\n"
        "result = {}\n"
        "try:\n"
        "    result['read'] = open(secret, encoding='utf-8').read()\n"
        "except OSError as e:\n"
        "    result['read_err'] = e.errno\n"
        "try:\n"
        "    p = os.path.join(writable, 'ok.txt')\n"
        "    open(p, 'w', encoding='utf-8').write('ok')\n"
        "    result['write'] = 'ok'\n"
        "except OSError as e:\n"
        "    result['write_err'] = e.errno\n"
        "try:\n"
        "    s = socket.create_connection(('127.0.0.1', port), timeout=1)\n"
        "    s.close()\n"
        "    result['net'] = 'ok'\n"
        "except OSError as e:\n"
        "    result['net_err'] = e.errno\n"
        "    result['net_winerror'] = getattr(e, 'winerror', None)\n"
        "    result['net_exc'] = type(e).__name__\n"
        "open(result_path, 'w', encoding='utf-8').write(repr(result))\n",
        encoding="utf-8",
    )
    identity = None
    buf = None
    log_file = None
    try:
        identity, _labels = prepare_windows_worker_isolation(
            writable,
            profile_name="jarvis.test.enforcement.ac",
            extra_read_paths=(child_py,),
        )
        grant_container_access(
            identity.sid_text,
            read_paths=(child_py.parent,),
            writable_root=writable,
        )
        caps = SECURITY_CAPABILITIES()
        caps.AppContainerSid = identity.sid
        size = SIZE_T()
        kernel32.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
        buf = (ctypes.c_byte * size.value)()
        if not kernel32.InitializeProcThreadAttributeList(buf, 1, 0, ctypes.byref(size)):
            raise AssertionError("InitializeProcThreadAttributeList failed")
        if isolate and not kernel32.UpdateProcThreadAttribute(
            buf, 0, PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES,
            ctypes.byref(caps), ctypes.sizeof(caps), None, None,
        ):
            raise AssertionError("UpdateProcThreadAttribute failed")
        log_file = open(log_path, "wb")
        raw = msvcrt.get_osfhandle(log_file.fileno())
        kernel32.SetHandleInformation(wintypes.HANDLE(raw), HANDLE_FLAG_INHERIT, HANDLE_FLAG_INHERIT)
        si = STARTUPINFOEXW()
        si.StartupInfo.cb = ctypes.sizeof(STARTUPINFOEXW)
        si.StartupInfo.dwFlags = STARTF_USESTDHANDLES
        si.StartupInfo.hStdOutput = wintypes.HANDLE(raw)
        si.StartupInfo.hStdError = wintypes.HANDLE(raw)
        si.lpAttributeList = ctypes.cast(buf, wintypes.LPVOID)
        from core.kernel.worker_windows_isolation import isolated_python_executable
        interpreter = str(isolated_python_executable())
        cmdline = ctypes.create_unicode_buffer(f'"{interpreter}" -I "{child_py}"')
        pi = PROCESS_INFORMATION()
        flags = CREATE_UNICODE_ENVIRONMENT | CREATE_NEW_PROCESS_GROUP
        if isolate:
            flags |= EXTENDED_STARTUPINFO_PRESENT
        ok = kernel32.CreateProcessW(
            None, cmdline, None, None, True, flags, None, str(writable),
            ctypes.byref(si), ctypes.byref(pi),
        )
        if not ok:
            raise AssertionError(f"CreateProcessW failed: {ctypes.get_last_error()}")
        kernel32.WaitForSingleObject(pi.hProcess, 20000)
        exit_code = wintypes.DWORD()
        kernel32.GetExitCodeProcess(pi.hProcess, ctypes.byref(exit_code))
        kernel32.CloseHandle(pi.hThread)
        kernel32.CloseHandle(pi.hProcess)
        log_file.close()
        log_file = None
        output = ""
        if result_path.exists():
            output = result_path.read_text(encoding="utf-8", errors="replace").strip()
        elif log_path.exists():
            output = log_path.read_text(encoding="utf-8", errors="replace").strip()
        payload = ast.literal_eval(output) if output.startswith("{") else {}
        return {"exit": int(exit_code.value), "payload": payload, "output": output}
    finally:
        if log_file is not None:
            log_file.close()
        if buf is not None:
            kernel32.DeleteProcThreadAttributeList(buf)
        listener.close()
        if identity is not None:
            identity.close()
        subprocess.run(["cmd", "/c", "rmdir", "/s", "/q", str(root)], capture_output=True)


if __name__ == "__main__":
    unittest.main()
