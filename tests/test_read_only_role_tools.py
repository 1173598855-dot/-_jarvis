"""Tests for the fixed read-only role tool catalog."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from core.brain.read_only_role_tools import create_read_only_role_tool_broker
from core.brain.role_registry import create_default_registry
from core.contracts.role_tool_protocol import RoleToolCall


class TestReadOnlyRoleTools(unittest.TestCase):
    def setUp(self):
        self.registry = create_default_registry()
        self.manager = Mock()
        self.manager.list_models.return_value = []

    @staticmethod
    def invoke(broker, profile, name, arguments=None):
        return broker.invoke(
            profile,
            RoleToolCall(name, arguments or {}, 0, 0, "call-1"),
        )

    def make_broker(self, memory_dir, repository_root):
        return create_read_only_role_tool_broker(
            self.manager,
            memory_dir=memory_dir,
            repository_root=repository_root,
            role_names=[profile.name for profile in self.registry.list_roles()],
        )

    def test_catalog_exposes_only_declared_read_only_definitions(self):
        with tempfile.TemporaryDirectory() as root:
            broker = self.make_broker(Path(root) / "memory", root)
            engineer = self.registry.get("engineer")

            authorized = broker.authorized_tools(engineer)
            definitions = broker.authorized_definitions(engineer)

        self.assertIn("repository_metadata", authorized)
        self.assertIn("system_status", authorized)
        self.assertNotIn("terminal_executor", authorized)
        self.assertEqual(
            [definition.name for definition in definitions],
            authorized,
        )
        for definition in definitions:
            self.assertEqual(definition.parameters["type"], "object")
            self.assertFalse(definition.parameters["additionalProperties"])

    def test_model_list_uses_trusted_manager_and_honors_limit(self):
        self.manager.list_models.return_value = [
            SimpleNamespace(
                name=f"model-{index}",
                size=index,
                digest=f"digest-{index}",
                modified_at="today",
            )
            for index in range(4)
        ]
        with tempfile.TemporaryDirectory() as root:
            broker = self.make_broker(Path(root) / "memory", root)
            result = self.invoke(
                broker,
                self.registry.get("engineer"),
                "model_list",
                {"limit": 2},
            )

        self.manager.list_models.assert_called_once_with()
        self.assertEqual(len(result["models"]), 2)
        self.assertEqual(result["models"][0]["name"], "model-0")

    def test_model_list_consumes_only_the_requested_number_of_models(self):
        consumed = []

        def models():
            for index in range(100):
                consumed.append(index)
                yield SimpleNamespace(
                    name=f"model-{index}",
                    size=index,
                    digest=f"digest-{index}",
                    modified_at="today",
                )

        self.manager.list_models.return_value = models()
        with tempfile.TemporaryDirectory() as root:
            broker = self.make_broker(Path(root) / "memory", root)
            result = self.invoke(
                broker,
                self.registry.get("engineer"),
                "model_list",
                {"limit": 2},
            )

        self.assertEqual(len(result["models"]), 2)
        self.assertEqual(consumed, [0, 1])

    def test_memory_search_is_bounded_redacted_and_does_not_create_missing_root(self):
        with tempfile.TemporaryDirectory() as root:
            memory_dir = Path(root) / "missing-memory"
            broker = self.make_broker(memory_dir, root)
            engineer = self.registry.get("engineer")

            empty = self.invoke(
                broker,
                engineer,
                "memory_search",
                {"query": "needle", "limit": 5},
            )
            self.assertEqual(empty["results"], [])
            self.assertFalse(memory_dir.exists())

            memory_dir.mkdir()
            (memory_dir / "MEMORY.md").write_text("# Memory Index\n", encoding="utf-8")
            (memory_dir / "user_fixture.md").write_text(
                "---\nname: Match\ntype: user\nimportance: 0.5\n---\n\n"
                "needle password=q " + ("x" * 1000),
                encoding="utf-8",
            )
            broker = self.make_broker(memory_dir, root)
            found = self.invoke(
                broker,
                engineer,
                "memory_search",
                {"query": "needle", "limit": 1},
            )

        self.assertEqual(len(found["results"]), 1)
        serialized = str(found)
        self.assertNotIn("password=q", serialized)
        self.assertLessEqual(len(found["results"][0]["snippet"]), 512)

    def test_memory_search_rejects_external_symlink_entries(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            memory_dir = root_path / "memory"
            memory_dir.mkdir()
            (memory_dir / "MEMORY.md").write_text("# Memory Index\n", encoding="utf-8")
            external = root_path / "outside.md"
            external.write_text(
                "---\nname: External\ntype: user\nimportance: 0.5\n---\n\n"
                "outside-needle",
                encoding="utf-8",
            )
            link = memory_dir / "user_external.md"
            try:
                link.symlink_to(external)
            except (NotImplementedError, OSError) as error:
                self.skipTest(f"symlink creation is unavailable: {error}")

            broker = self.make_broker(memory_dir, root)
            found = self.invoke(
                broker,
                self.registry.get("engineer"),
                "memory_search",
                {"query": "outside-needle"},
            )

        self.assertEqual(found["results"], [])

    def test_memory_search_passes_explicit_scan_and_byte_caps(self):
        with tempfile.TemporaryDirectory() as root, patch(
            "core.brain.read_only_role_tools.MemoryStore"
        ) as store_type:
            memory_dir = Path(root) / "memory"
            memory_dir.mkdir()
            (memory_dir / "MEMORY.md").write_text("# Memory Index\n", encoding="utf-8")
            store_type.return_value.load.return_value = []
            broker = self.make_broker(memory_dir, root)

            result = self.invoke(
                broker,
                self.registry.get("engineer"),
                "memory_search",
                {"query": "needle"},
            )

        self.assertEqual(result["results"], [])
        store_type.assert_called_once_with(
            memory_dir=str(memory_dir.resolve()),
            read_only=True,
        )
        load_kwargs = store_type.return_value.load.call_args.kwargs
        self.assertEqual(
            set(load_kwargs),
            {
                "max_directory_entries",
                "max_files",
                "max_file_bytes",
                "max_total_bytes",
            },
        )
        self.assertTrue(
            all(type(value) is int and value > 0 for value in load_kwargs.values())
        )

    def test_status_and_repository_handlers_return_bounded_trusted_snapshots(self):
        snapshot = SimpleNamespace(
            head="a" * 40,
            branch="feature",
            dirty_paths=tuple(f"path-{index}" for index in range(80)),
        )
        with tempfile.TemporaryDirectory() as root, patch(
            "core.brain.read_only_role_tools.GitWorkspaceInspector"
        ) as inspector_type:
            inspector_type.return_value.snapshot.return_value = snapshot
            broker = self.make_broker(Path(root) / "memory", root)
            architect = self.registry.get("architect")
            system = self.invoke(broker, architect, "system_status")
            repository = self.invoke(broker, architect, "repository_metadata")
            orchestrator = self.invoke(broker, architect, "orchestrator_status")

        inspector_type.assert_called_once_with(Path(root).resolve())
        self.assertIn("platform", system)
        self.assertIn("cpu_count", system)
        self.assertIn("disk", system)
        self.assertEqual(repository["head"], "a" * 40)
        self.assertLessEqual(len(repository["dirty_paths"]), 50)
        self.assertTrue(orchestrator["worker_isolation"])
        self.assertEqual(orchestrator["roles"], sorted(orchestrator["roles"]))


if __name__ == "__main__":
    unittest.main()
