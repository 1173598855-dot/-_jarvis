"""Capability manifest and local registry contract tests."""

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from core.kernel.capability_manifest import (  # noqa: E402
    CapabilityHealth,
    CapabilityKind,
    CapabilityLifecycle,
    CapabilityRecord,
    CapabilityRisk,
    CapabilityValidationError,
)
from core.kernel.capability_registry import CapabilityRegistry  # noqa: E402


class TestCapabilityRecord(unittest.TestCase):
    def test_public_record_uses_relative_paths_and_explicit_unknown_metadata(self):
        record = CapabilityRecord.create(
            capability_id="skill:example",
            kind=CapabilityKind.SKILL,
            name="example",
            version=None,
            description="Example skill",
            relative_path="skills/example",
            entrypoint="skills/example/SKILL.md",
            lifecycle=CapabilityLifecycle.DISCOVERED,
            permissions=("memory_read",),
            compatibility={"jarvis_api": ">=1.0.0"},
            compatibility_status="unknown",
            source_url=None,
            license_name=None,
            sha256="a" * 64,
            provenance_status="incomplete",
            health=CapabilityHealth.DEGRADED,
            health_issues=("provenance_incomplete",),
            risk=CapabilityRisk.MEDIUM,
            risk_reasons=("provenance_incomplete",),
        )

        body = record.to_public_dict()

        self.assertEqual(body["schema_version"], 1)
        self.assertEqual(body["relative_path"], "skills/example")
        self.assertIsNone(body["version"])
        self.assertIsNone(body["provenance"]["source_url"])
        self.assertNotIn(str(ROOT), json.dumps(body))

    def test_record_rejects_absolute_parent_and_backslash_paths(self):
        for relative_path in ("C:/outside", "/outside", "../outside", "skills\\outside"):
            with self.subTest(relative_path=relative_path):
                with self.assertRaises(CapabilityValidationError):
                    CapabilityRecord.create(
                        capability_id="skill:example",
                        kind=CapabilityKind.SKILL,
                        name="example",
                        version=None,
                        description="",
                        relative_path=relative_path,
                        entrypoint=None,
                    )

    def test_record_normalizes_sorted_unique_permissions_and_issues(self):
        record = CapabilityRecord.create(
            capability_id="plugin:logger",
            kind=CapabilityKind.PLUGIN,
            name="logger",
            version="1.0.0",
            description="Logger",
            relative_path="plugins/logger",
            entrypoint="plugins/logger/plugin.py",
            permissions=("event_bus", "file_read", "event_bus"),
            health_issues=("missing_license", "missing_source", "missing_license"),
            risk_reasons=("native_runtime", "missing_source", "native_runtime"),
        )

        self.assertEqual(record.permissions, ("event_bus", "file_read"))
        self.assertEqual(record.health_issues, ("missing_license", "missing_source"))
        self.assertEqual(record.risk_reasons, ("missing_source", "native_runtime"))

    def test_record_rejects_untyped_enum_values(self):
        with self.assertRaises(CapabilityValidationError):
            CapabilityRecord.create(
                capability_id="skill:example",
                kind=CapabilityKind.SKILL,
                name="example",
                version=None,
                description="",
                relative_path="skills/example",
                entrypoint=None,
                lifecycle="discovered",
            )


class TestCapabilityRegistry(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        (self.root / "skills" / "memory-keeper").mkdir(parents=True)
        (self.root / "plugins" / "event-logger").mkdir(parents=True)
        (self.root / "frontend" / "src" / "components").mkdir(parents=True)

        (self.root / "skills" / "memory-keeper" / "SKILL.md").write_text(
            "# memory-keeper - local memory\n\n"
            "**来源**: [example/memory](https://github.com/example/memory)\n"
            "**许可证**: Apache-2.0\n\nKeeps memory searchable.\n",
            encoding="utf-8",
        )
        plugin = self.root / "plugins" / "event-logger"
        (plugin / "manifest.json").write_text(
            json.dumps({
                "plugin_id": "event-logger",
                "name": "Event Logger",
                "version": "1.0.0",
                "description": "Records lifecycle events.",
                "permissions": ["event_bus"],
                "runtime": "native",
                "entry_point": "plugin.py",
                "api_version": "1.0.0",
            }),
            encoding="utf-8",
        )
        (plugin / "plugin.py").write_text(
            "from pathlib import Path\n"
            "Path(__file__).with_name('imported.txt').write_text('bad')\n",
            encoding="utf-8",
        )
        (self.root / "frontend" / "src" / "components" / "StatusIndicator.tsx").write_text(
            "export function StatusIndicator() { return null; }\n",
            encoding="utf-8",
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_snapshot_discovers_skills_plugins_and_ui_without_importing_code(self):
        snapshot = CapabilityRegistry(self.root).snapshot()

        self.assertEqual(
            [record.capability_id for record in snapshot.records],
            [
                "plugin:event-logger",
                "skill:memory-keeper",
                "ui_component:status-indicator",
            ],
        )
        self.assertEqual(snapshot.schema_version, 1)
        self.assertFalse(
            (self.root / "plugins" / "event-logger" / "imported.txt").exists()
        )

    def test_snapshot_is_deterministic_and_hash_changes_with_content(self):
        registry = CapabilityRegistry(self.root)
        first = registry.snapshot()
        second = registry.snapshot()
        self.assertEqual(first.to_public_dict(), second.to_public_dict())

        skill_file = self.root / "skills" / "memory-keeper" / "SKILL.md"
        before = next(record for record in first.records if record.kind is CapabilityKind.SKILL)
        skill_file.write_text(skill_file.read_text(encoding="utf-8") + "updated\n", encoding="utf-8")
        after = next(
            record for record in registry.snapshot().records
            if record.kind is CapabilityKind.SKILL
        )
        self.assertNotEqual(before.sha256, after.sha256)

    def test_generated_files_do_not_change_content_digest(self):
        registry = CapabilityRegistry(self.root)
        before = registry.snapshot().records[0].sha256
        cache = self.root / "plugins" / "event-logger" / "__pycache__"
        cache.mkdir()
        (cache / "plugin.pyc").write_bytes(b"generated")
        after = registry.snapshot().records[0].sha256
        self.assertEqual(before, after)

    def test_direct_ui_component_digest_does_not_include_siblings(self):
        registry = CapabilityRegistry(self.root)
        before = next(
            item for item in registry.snapshot().records
            if item.capability_id == "ui_component:status-indicator"
        ).sha256
        (self.root / "frontend" / "src" / "components" / "Other.tsx").write_text(
            "export function Other() { return null; }\n",
            encoding="utf-8",
        )
        after = next(
            item for item in registry.snapshot().records
            if item.capability_id == "ui_component:status-indicator"
        ).sha256
        self.assertEqual(before, after)

    def test_normalized_identifier_collision_is_bounded_to_one_record(self):
        components = self.root / "frontend" / "src" / "components"
        (components / "FooBar.tsx").write_text("export const FooBar = 1;\n", encoding="utf-8")
        (components / "foo-bar.tsx").write_text("export const duplicate = 1;\n", encoding="utf-8")

        snapshot = CapabilityRegistry(self.root).snapshot()

        duplicates = [
            record for record in snapshot.records
            if record.capability_id == "ui_component:foo-bar"
        ]
        self.assertEqual(len(duplicates), 1)
        self.assertIn("capability_duplicate:ui_component:foo-bar", snapshot.issues)

    def test_malformed_plugin_is_reported_invalid_without_stopping_snapshot(self):
        broken = self.root / "plugins" / "broken"
        broken.mkdir()
        (broken / "manifest.json").write_text("{", encoding="utf-8")

        snapshot = CapabilityRegistry(self.root).snapshot()
        record = next(item for item in snapshot.records if item.capability_id == "plugin:broken")

        self.assertEqual(record.health, CapabilityHealth.INVALID)
        self.assertEqual(record.risk, CapabilityRisk.HIGH)
        self.assertIn("manifest_invalid", record.health_issues)

    def test_missing_plugin_entrypoint_is_invalid(self):
        (self.root / "plugins" / "event-logger" / "plugin.py").unlink()
        record = CapabilityRegistry(self.root).snapshot().records[0]
        self.assertEqual(record.health, CapabilityHealth.INVALID)
        self.assertIn("entrypoint_missing", record.health_issues)

    @unittest.skipUnless(hasattr(Path, "symlink_to"), "symlinks unavailable")
    def test_symlinked_capability_is_not_followed(self):
        external = self.root / "external"
        external.mkdir()
        (external / "SKILL.md").write_text("# external\n", encoding="utf-8")
        linked = self.root / "skills" / "linked"
        try:
            linked.symlink_to(external, target_is_directory=True)
        except OSError as error:
            self.skipTest(f"symlink creation unavailable: {error}")

        snapshot = CapabilityRegistry(self.root).snapshot()

        self.assertNotIn("skill:linked", [item.capability_id for item in snapshot.records])
        self.assertIn("skill_symlink_rejected:linked", snapshot.issues)

    @unittest.skipUnless(hasattr(Path, "symlink_to"), "symlinks unavailable")
    def test_symlinked_capability_root_is_not_followed(self):
        import shutil

        external = self.root / "external-skills"
        external.mkdir()
        (external / "outside").mkdir()
        (external / "outside" / "SKILL.md").write_text("# outside\n", encoding="utf-8")
        skills_root = self.root / "skills"
        shutil.rmtree(skills_root)
        try:
            skills_root.symlink_to(external, target_is_directory=True)
        except OSError as error:
            self.skipTest(f"symlink creation unavailable: {error}")

        snapshot = CapabilityRegistry(self.root).snapshot()

        self.assertNotIn("skill:outside", [item.capability_id for item in snapshot.records])
        self.assertIn("skill_root_symlink_rejected", snapshot.issues)

    def test_public_snapshot_never_contains_absolute_root(self):
        payload = CapabilityRegistry(self.root).snapshot().to_public_dict()
        self.assertNotIn(str(self.root), json.dumps(payload))


if __name__ == "__main__":
    unittest.main()
