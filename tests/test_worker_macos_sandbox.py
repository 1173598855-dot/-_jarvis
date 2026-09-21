"""Contract tests for the parent-owned macOS Worker sandbox."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path, PurePosixPath

from core.kernel.worker_macos_sandbox import (
    MacOSSandbox,
    WorkerMacOSSandboxError,
    macos_sandbox_profile,
)
from core.kernel.worker_staging import WorkerStagingError, stage_worker_tree


class TestMacOSSandboxContract(unittest.TestCase):
    def test_profile_denies_network_and_limits_file_access(self) -> None:
        profile = macos_sandbox_profile(
            read_paths=(PurePosixPath("/Library/Frameworks/Python.framework"),),
            writable_root=PurePosixPath("/private/tmp/jarvis-worker"),
        )

        self.assertTrue(profile.startswith("(version 1)\n(deny default)\n"))
        self.assertIn(
            '(allow file-read* (subpath "/Library/Frameworks/Python.framework"))',
            profile,
        )
        self.assertIn(
            '(allow file-read* (subpath "/private/tmp/jarvis-worker"))',
            profile,
        )
        self.assertIn(
            '(allow file-write* (subpath "/private/tmp/jarvis-worker"))',
            profile,
        )
        self.assertIn(
            '(allow file-map-executable (subpath "/Library/Frameworks/Python.framework"))',
            profile,
        )
        self.assertNotIn("process-exec", profile)
        self.assertNotIn("network-outbound", profile)
        self.assertNotIn("network-inbound", profile)

        executable_profile = macos_sandbox_profile(
            read_paths=(PurePosixPath("/Library/Frameworks/Python.framework"),),
            writable_root=PurePosixPath("/private/tmp/jarvis-worker"),
            executable_path=PurePosixPath(
                "/Library/Frameworks/Python.framework/Versions/3.11/bin/python"
            ),
        )
        self.assertIn(
            '(allow process-exec (literal "/Library/Frameworks/Python.framework/Versions/3.11/bin/python"))',
            executable_profile,
        )

    def test_profile_escapes_seatbelt_literals_and_rejects_invalid_paths(self) -> None:
        profile = macos_sandbox_profile(
            read_paths=(PurePosixPath('/private/var/worker "quoted"'),),
            writable_root=PurePosixPath("/private/tmp/worker"),
        )
        self.assertIn(
            '(allow file-read* (subpath "/private/var/worker \\\"quoted\\\""))',
            profile,
        )

        with self.assertRaises(WorkerMacOSSandboxError):
            macos_sandbox_profile(
                read_paths=(PurePosixPath("relative/runtime"),),
                writable_root=PurePosixPath("/private/tmp/worker"),
            )
        with self.assertRaises(WorkerMacOSSandboxError):
            macos_sandbox_profile(
                read_paths=(PurePosixPath("/private/runtime"),),
                writable_root=PurePosixPath("relative/worker"),
            )

    def test_shared_staging_rejects_links_and_entry_overflow(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "destination"
            source.mkdir()
            (source / "one.txt").write_text("one", encoding="utf-8")
            with self.assertRaises(WorkerStagingError):
                stage_worker_tree(source, destination, entry_budget=0)

    def test_missing_launcher_fails_closed_and_removes_owned_root(self) -> None:
        created: list[Path] = []

        def make_temporary(**_kwargs: object) -> str:
            path = Path(tempfile.mkdtemp(prefix=".test-macos-sandbox-"))
            created.append(path)
            return str(path)

        with self.assertRaises(WorkerMacOSSandboxError):
            MacOSSandbox.create(
                launcher_lookup=lambda _name: None,
                temporary_directory=make_temporary,
                runtime_read_paths=(PurePosixPath("/usr/bin"),),
            )

        self.assertEqual(len(created), 1)
        self.assertFalse(created[0].exists())

    def test_spawn_wraps_command_with_profile_and_keeps_one_writable_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "sandbox"
            identity = MacOSSandbox(
                root=root,
                code_root=PurePosixPath("/private/tmp/jarvis-code"),
                writable_root=PurePosixPath("/private/tmp/jarvis-worker"),
                launcher="/usr/bin/sandbox-exec",
                profile="(version 1)\n(deny default)\n",
            )
            captured: dict[str, object] = {}

            def fake_popen(arguments, **kwargs):
                captured["arguments"] = arguments
                captured.update(kwargs)
                return object()

            process = identity.spawn(
                ["/usr/bin/python3", "worker.py"],
                cwd=identity.code_root,
                environment={"TMPDIR": str(identity.writable_root)},
                popen=fake_popen,
            )
            self.assertIsNotNone(process)
            self.assertEqual(
                captured["arguments"][:3],
                ["/usr/bin/sandbox-exec", "-p", identity.profile],
            )
            self.assertEqual(
                captured["arguments"][3:], ["/usr/bin/python3", "worker.py"]
            )
            self.assertEqual(captured["env"]["TMPDIR"], str(identity.writable_root))
            identity.close()
            self.assertFalse(root.exists())


if __name__ == "__main__":
    unittest.main()
