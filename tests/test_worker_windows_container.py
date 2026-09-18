"""Parent-owned Windows Worker container transport tests."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.kernel.worker_windows_container import (
    WindowsWorkerContainer,
    WorkerContainerError,
    container_environment,
    container_profile_name,
    stage_container_tree,
)
from core.kernel.worker_windows_isolation import WindowsAppContainerIdentity


class _FakeIdentityApi:
    def __init__(self) -> None:
        self.released = False
        self.deleted: list[str] = []

    def release_sid(self, _sid: object) -> None:
        self.released = True

    def delete_profile(self, name: str) -> None:
        self.deleted.append(name)


class _FakeGrant:
    def __init__(self) -> None:
        self.calls: list[tuple[object, tuple[Path, ...], tuple[Path, ...]]] = []

    def __call__(
        self,
        sid: object,
        *,
        read_paths: tuple[Path, ...],
        writable_paths: tuple[Path, ...],
    ) -> tuple[tuple[str, str], ...]:
        self.calls.append((sid, read_paths, writable_paths))
        return ()


class _FakeProcess:
    pid = 123


class TestWindowsContainerContract(unittest.TestCase):
    def test_container_environment_adds_required_local_app_data(self) -> None:
        with patch.dict(
            os.environ,
            {"LOCALAPPDATA": "C:\\Users\\worker\\AppData\\Local"},
            clear=False,
        ):
            environment = container_environment({"PATH": "C:\\Windows"})
        self.assertEqual(environment["PATH"], "C:\\Windows")
        self.assertEqual(
            environment["LOCALAPPDATA"], "C:\\Users\\worker\\AppData\\Local"
        )

    def test_container_environment_rejects_missing_required_variable(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(WorkerContainerError):
                container_environment({"PATH": "C:\\Windows"})

    def test_profile_names_are_unique_within_one_process(self) -> None:
        first = container_profile_name()
        second = container_profile_name()
        self.assertNotEqual(first, second)
        self.assertLessEqual(len(first), 64)

    def test_stage_rejects_links_before_copying(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            destination = root / "destination"
            source.mkdir()
            (source / "real.txt").write_text("ok", encoding="utf-8")
            try:
                (source / "linked.txt").symlink_to(source / "real.txt")
            except (OSError, NotImplementedError):
                self.skipTest("symlinks are unavailable")
            with self.assertRaises(WorkerContainerError):
                stage_container_tree(source, destination)
            self.assertFalse(destination.exists())

    def test_stage_rejects_entry_budget_overflow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            destination = root / "destination"
            source.mkdir()
            for index in range(3):
                (source / f"entry-{index}").write_text("ok", encoding="utf-8")
            with self.assertRaises(WorkerContainerError):
                stage_container_tree(source, destination, entry_budget=2)
            self.assertFalse(destination.exists())

    def test_create_grants_empty_stage_and_writable_root(self) -> None:
        api = _FakeIdentityApi()
        identity = WindowsAppContainerIdentity(
            name="jarvis.test.container",
            sid=object(),
            sid_text="S-1-15-2-9",
            created=True,
            api=api,
        )
        grant = _FakeGrant()

        def prepare(
            writable_root: Path,
            *,
            profile_name: str,
            grant,
        ) -> tuple[WindowsAppContainerIdentity, tuple[str, ...]]:
            self.assertTrue(writable_root.is_dir())
            self.assertTrue(profile_name)
            return identity, ("appcontainer",)

        with tempfile.TemporaryDirectory() as tmp:
            container = WindowsWorkerContainer.create(
                prepare=prepare,
                grant=grant,
                interpreter=Path(tmp) / "python.exe",
                verify_interpreter=lambda _path: True,
                temporary_directory=lambda **_kwargs: tmp,
            )
            self.assertEqual(len(grant.calls), 1)
            _sid, read_paths, writable_paths = grant.calls[0]
            self.assertEqual(len(read_paths), 1)
            self.assertEqual(len(writable_paths), 1)
            self.assertEqual(read_paths[0], container.code_root)
            self.assertEqual(writable_paths[0], container.writable_root)
            container.close()

        self.assertTrue(api.released)
        self.assertEqual(api.deleted, ["jarvis.test.container"])

    def test_stage_and_close_remove_container_owned_tree(self) -> None:
        api = _FakeIdentityApi()
        identity = WindowsAppContainerIdentity(
            name="jarvis.test.container.tree",
            sid=object(),
            sid_text="S-1-15-2-10",
            created=True,
            api=api,
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "worker.py").write_text("print('ok')", encoding="utf-8")
            container = WindowsWorkerContainer(
                identity=identity,
                root=root / "container",
                code_root=root / "container" / "code",
                writable_root=root / "container" / "tmp",
                interpreter=Path("python.exe"),
            )
            container.code_root.mkdir(parents=True)
            container.writable_root.mkdir()
            staged = container.stage(source, "worker")
            self.assertEqual(
                (staged / "worker.py").read_text(encoding="utf-8"), "print('ok')"
            )
            container.close()
            self.assertFalse(container.root.exists())

    def test_spawn_passes_identity_and_container_environment(self) -> None:
        api = _FakeIdentityApi()
        identity = WindowsAppContainerIdentity(
            name="jarvis.test.container.spawn",
            sid=object(),
            sid_text="S-1-15-2-11",
            created=True,
            api=api,
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            container = WindowsWorkerContainer(
                identity=identity,
                root=root,
                code_root=root / "code",
                writable_root=root / "tmp",
                interpreter=Path("python.exe"),
            )
            captured: dict[str, object] = {}

            def fake_popen(arguments, **kwargs):
                captured["arguments"] = arguments
                captured.update(kwargs)
                return _FakeProcess()

            process = container.spawn(
                ["python.exe", "worker.py"],
                cwd=root,
                environment={"PATH": "C:\\Windows"},
                popen=fake_popen,
            )

        self.assertIsInstance(process, _FakeProcess)
        self.assertEqual(captured["arguments"], ["python.exe", "worker.py"])
        self.assertIs(captured["app_container_sid"], identity.sid)
        self.assertEqual(captured["env"]["LOCALAPPDATA"], os.environ["LOCALAPPDATA"])


if __name__ == "__main__":
    unittest.main()
