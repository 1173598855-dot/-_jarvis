"""Capability manifest and local registry contract tests."""

import inspect
import json
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from core.contracts.role_tool_catalog import (  # noqa: E402
    ROLE_TOOL_CATALOG,
    RoleToolAssembly,
)
from core.kernel import capability_registry as capability_registry_module  # noqa: E402
from core.kernel.capability_manifest import (  # noqa: E402
    CapabilityHealth,
    CapabilityKind,
    CapabilityLifecycle,
    CapabilityRecord,
    CapabilityRisk,
    CapabilitySnapshot,
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

    def test_record_rejects_surrogates_in_public_text(self):
        for field_name in ("name", "version", "description", "source_url"):
            arguments = {
                "capability_id": "skill:example",
                "kind": CapabilityKind.SKILL,
                "name": "example",
                "version": "1.0.0",
                "description": "description",
                "relative_path": "skills/example",
                "entrypoint": None,
                "source_url": "https://example.com/skill",
            }
            arguments[field_name] = "invalid\ud800text"

            with self.subTest(field_name=field_name):
                with self.assertRaises(CapabilityValidationError) as raised:
                    CapabilityRecord.create(**arguments)
                self.assertEqual(raised.exception.code, "field_unicode_invalid")


class TestCapabilityRegistry(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        (self.root / "skills" / "memory-keeper").mkdir(parents=True)
        (self.root / "plugins" / "event-logger").mkdir(parents=True)
        (self.root / "frontend" / "src" / "components").mkdir(parents=True)
        (self.root / "src" / "core" / "brain").mkdir(parents=True)

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
        (self.root / "src" / "core" / "brain" / "read_only_role_tools.py").write_text(
            "# trusted built-in role tools\n",
            encoding="utf-8",
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_snapshot_discovers_all_public_kinds_without_importing_code(self):
        snapshot = CapabilityRegistry(self.root).snapshot()

        self.assertEqual(
            [record.capability_id for record in snapshot.records],
            [
                "plugin:event-logger",
                "role_tool:memory_search",
                "role_tool:model_list",
                "role_tool:orchestrator_status",
                "role_tool:repository_metadata",
                "role_tool:system_status",
                "skill:memory-keeper",
                "ui_component:status-indicator",
            ],
        )
        self.assertEqual(snapshot.schema_version, 1)
        self.assertFalse(
            (self.root / "plugins" / "event-logger" / "imported.txt").exists()
        )

    def test_snapshot_uses_only_finite_binary_content_reads(self):
        expected = CapabilityRegistry(self.root).snapshot().to_public_dict()
        original_open = Path.open
        read_sizes = []

        class _ReadGuard:
            def __init__(self, handle):
                self._handle = handle
                self._read_count = 0

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self._handle.close()
                if args[0] is None and self._read_count != 1:
                    raise AssertionError(
                        "each capability file must use exactly one content read"
                    )
                return False

            def read(self, size=-1):
                self._read_count += 1
                if self._read_count != 1:
                    raise AssertionError(
                        "capability files must not be read to EOF in chunks"
                    )
                if size != capability_registry_module._MAX_FILE_BYTES + 1:
                    raise AssertionError(
                        "capability reads must use the one-byte sentinel budget"
                    )
                read_sizes.append(size)
                return self._handle.read(size)

        def guarded_open(path, mode="r", *args, **kwargs):
            handle = original_open(path, mode, *args, **kwargs)
            if mode != "rb":
                handle.close()
                raise AssertionError("capability reads must use binary mode")
            return _ReadGuard(handle)

        with patch.object(Path, "open", guarded_open):
            actual = CapabilityRegistry(self.root).snapshot().to_public_dict()

        self.assertEqual(actual, expected)
        self.assertTrue(read_sizes)
        self.assertTrue(all(
            size == capability_registry_module._MAX_FILE_BYTES + 1
            for size in read_sizes
        ))

        digest_fixture = self.root / "digest-fixture.bin"
        digest_fixture.write_bytes(b"abc")
        self.assertEqual(
            capability_registry_module._hash_files([
                ("file.txt", digest_fixture),
            ]),
            "18f76c82a7af6798ee10dd955e3ccc4922cbc3a14e0ac3ce833eb9e6c23be17f",
        )

    def test_hash_rejects_growth_after_underreported_size_check(self):
        target = self.root / "growing-capability.bin"
        target.write_bytes(
            b"x" * (capability_registry_module._MAX_FILE_BYTES + 2)
        )
        real_stat = target.stat()

        with patch.object(
            Path,
            "stat",
            return_value=SimpleNamespace(st_mode=real_stat.st_mode, st_size=1),
        ):
            with self.assertRaises(CapabilityValidationError) as raised:
                capability_registry_module._hash_file(target)

        self.assertEqual(raised.exception.code, "tree_file_too_large")

    def test_plugin_parser_resource_errors_are_invalid_candidates(self):
        cases = {
            "a-deep-json": (
                "{" +
                '"plugin_id":"a-deep-json",' +
                '"name":"deep",' +
                '"version":"1.0.0",' +
                '"entry_point":"plugin.py",' +
                '"nested":' + "[" * 5000 + "0" + "]" * 5000 +
                "}"
            ),
            "a-parser-value-error": (
                "{"
                '"plugin_id":"a-parser-value-error",'
                '"name":"value error",'
                '"version":"1.0.0",'
                '"entry_point":"plugin.py",'
                '"huge_integer":' + "9" * 5000 +
                "}"
            ),
        }

        for plugin_id, payload in cases.items():
            with self.subTest(plugin_id=plugin_id):
                directory = self.root / "plugins" / plugin_id
                directory.mkdir()
                manifest_path = directory / "manifest.json"
                manifest_path.write_text(payload, encoding="utf-8")

                try:
                    snapshot = CapabilityRegistry(self.root).snapshot()
                finally:
                    manifest_path.unlink()
                    directory.rmdir()

                plugins = {
                    record.capability_id: record
                    for record in snapshot.records
                    if record.kind is CapabilityKind.PLUGIN
                }
                self.assertIn("plugin:event-logger", plugins)
                self.assertIs(
                    plugins["plugin:event-logger"].lifecycle,
                    CapabilityLifecycle.DISCOVERED,
                )
                invalid = plugins[f"plugin:{plugin_id}"]
                self.assertIs(invalid.lifecycle, CapabilityLifecycle.INVALID)
                self.assertEqual(invalid.health_issues, ("manifest_invalid",))

        exact_skill = self.root / "skills" / "a-exact-limit-skill"
        exact_skill.mkdir()
        exact_skill_file = exact_skill / "SKILL.md"
        exact_skill_file.write_bytes(
            b"# exact-limit\n"
            + b"x" * (
                capability_registry_module._MAX_FILE_BYTES
                - len(b"# exact-limit\n")
            )
        )
        oversized_skill = self.root / "skills" / "a-too-large-skill"
        oversized_skill.mkdir()
        oversized_skill_file = oversized_skill / "SKILL.md"
        oversized_skill_file.write_bytes(
            b"x" * (capability_registry_module._MAX_FILE_BYTES + 1)
        )
        oversized_plugin = self.root / "plugins" / "a-too-large-plugin"
        oversized_plugin.mkdir()
        oversized_plugin_file = oversized_plugin / "manifest.json"
        oversized_plugin_file.write_bytes(
            b"x" * (capability_registry_module._MAX_FILE_BYTES + 1)
        )
        try:
            snapshot = CapabilityRegistry(self.root).snapshot()
        finally:
            exact_skill_file.unlink()
            exact_skill.rmdir()
            oversized_skill_file.unlink()
            oversized_skill.rmdir()
            oversized_plugin_file.unlink()
            oversized_plugin.rmdir()

        self.assertIn(
            "skill_invalid:a-too-large-skill:manifest_too_large",
            snapshot.issues,
        )
        exact_record = next(
            record for record in snapshot.records
            if record.capability_id == "skill:a-exact-limit-skill"
        )
        self.assertIs(exact_record.lifecycle, CapabilityLifecycle.DISCOVERED)
        invalid_by_id = {
            record.capability_id: record
            for record in snapshot.records
            if record.lifecycle is CapabilityLifecycle.INVALID
        }
        self.assertEqual(
            invalid_by_id["plugin:a-too-large-plugin"].health_issues,
            ("manifest_too_large",),
        )

    def test_role_tool_records_are_enabled_verified_static_inventory(self):
        snapshot = CapabilityRegistry(self.root).snapshot()
        records = [
            record for record in snapshot.records
            if record.kind is CapabilityKind.ROLE_TOOL
        ]

        self.assertEqual(
            [record.capability_id for record in records],
            [entry.capability_id for entry in ROLE_TOOL_CATALOG],
        )
        for record, entry in zip(records, ROLE_TOOL_CATALOG):
            with self.subTest(capability_id=record.capability_id):
                self.assertEqual(record.name, entry.definition.name)
                self.assertEqual(record.description, entry.definition.description)
                self.assertEqual(
                    record.relative_path,
                    "src/core/brain/read_only_role_tools.py",
                )
                self.assertEqual(record.entrypoint, record.relative_path)
                self.assertIs(record.lifecycle, CapabilityLifecycle.ENABLED)
                self.assertEqual(record.permissions, entry.permissions)
                self.assertEqual(record.provenance_status, "verified")
                self.assertEqual(record.sha256, entry.descriptor_sha256)
                self.assertIs(record.health, CapabilityHealth.HEALTHY)
                self.assertIs(record.risk, CapabilityRisk.LOW)

    def test_role_tool_assembly_is_exact_and_ignores_unrelated_degradation(self):
        registry = CapabilityRegistry(self.root)
        snapshot = registry.snapshot()
        skill = next(
            record for record in snapshot.records
            if record.kind is CapabilityKind.SKILL
        )
        degraded = replace(
            skill,
            health=CapabilityHealth.DEGRADED,
            health_issues=("fixture_degraded",),
        )
        snapshot = CapabilitySnapshot.create(
            degraded if record is skill else record
            for record in snapshot.records
        )

        with patch.object(registry, "snapshot", return_value=snapshot):
            assembly = registry.role_tool_assembly()

        self.assertEqual(assembly, RoleToolAssembly.for_catalog())

    def test_role_tool_assembly_rejects_untrusted_record_variants(self):
        registry = CapabilityRegistry(self.root)
        snapshot = registry.snapshot()
        role_records = [
            record for record in snapshot.records
            if record.kind is CapabilityKind.ROLE_TOOL
        ]
        first = role_records[0]
        other_records = [
            record for record in snapshot.records
            if record is not first
        ]
        unknown = CapabilityRecord.create(
            capability_id="role_tool:unknown",
            kind=CapabilityKind.ROLE_TOOL,
            name="unknown",
            version=None,
            description="Unknown role tool",
            relative_path="src/core/brain/read_only_role_tools.py",
            entrypoint="src/core/brain/read_only_role_tools.py",
            lifecycle=CapabilityLifecycle.ENABLED,
            provenance_status="verified",
            sha256="f" * 64,
            health=CapabilityHealth.HEALTHY,
            risk=CapabilityRisk.LOW,
        )
        variants = {
            "missing": CapabilitySnapshot.create(other_records),
            "extra": CapabilitySnapshot.create([*snapshot.records, unknown]),
            "duplicate_issue": CapabilitySnapshot.create(
                snapshot.records,
                issues=(f"capability_duplicate:{first.capability_id}",),
            ),
            "disabled": CapabilitySnapshot.create([
                replace(first, lifecycle=CapabilityLifecycle.DISABLED),
                *other_records,
            ]),
            "degraded": CapabilitySnapshot.create([
                replace(first, health=CapabilityHealth.DEGRADED),
                *other_records,
            ]),
            "higher_risk": CapabilitySnapshot.create([
                replace(first, risk=CapabilityRisk.MEDIUM),
                *other_records,
            ]),
            "unverified": CapabilitySnapshot.create([
                replace(first, provenance_status="complete"),
                *other_records,
            ]),
            "digest_mismatch": CapabilitySnapshot.create([
                replace(first, sha256="0" * 64),
                *other_records,
            ]),
        }

        for label, invalid_snapshot in variants.items():
            with self.subTest(label=label):
                with patch.object(
                    registry,
                    "snapshot",
                    return_value=invalid_snapshot,
                ):
                    with self.assertRaises(CapabilityValidationError) as raised:
                        registry.role_tool_assembly()
                self.assertEqual(
                    raised.exception.code,
                    "role_tool_assembly_invalid",
                )

    def test_missing_role_tool_source_fails_closed_without_records(self):
        source = self.root / "src" / "core" / "brain" / "read_only_role_tools.py"
        source.unlink()

        snapshot = CapabilityRegistry(self.root).snapshot()

        self.assertFalse(any(
            record.kind is CapabilityKind.ROLE_TOOL
            for record in snapshot.records
        ))
        self.assertIn("role_tool_source_missing", snapshot.issues)

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

    def test_snapshot_cache_coalesces_concurrent_scans_and_expires(self):
        self.assertIn(
            "cache_ttl_seconds",
            inspect.signature(CapabilityRegistry).parameters,
        )
        now = [0.0]
        registry = CapabilityRegistry(
            self.root,
            cache_ttl_seconds=5.0,
            clock=lambda: now[0],
        )
        original_scan = registry._build_snapshot
        scan_started = threading.Event()
        release_scan = threading.Event()

        def slow_scan():
            scan_started.set()
            self.assertTrue(release_scan.wait(timeout=2))
            return original_scan()

        with patch.object(registry, "_build_snapshot", side_effect=slow_scan) as scan:
            with ThreadPoolExecutor(max_workers=4) as pool:
                futures = [pool.submit(registry.snapshot) for _ in range(4)]
                self.assertTrue(scan_started.wait(timeout=2))
                release_scan.set()
                snapshots = [future.result(timeout=2) for future in futures]

            self.assertEqual(scan.call_count, 1)
            self.assertTrue(all(snapshot is snapshots[0] for snapshot in snapshots))

            now[0] = 6.0
            registry.snapshot()
            self.assertEqual(scan.call_count, 2)

    def test_direct_child_scan_is_bounded_per_capability_kind(self):
        for name in ("alpha", "beta"):
            directory = self.root / "skills" / name
            directory.mkdir()
            (directory / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")

        self.assertTrue(hasattr(capability_registry_module, "_MAX_CHILDREN"))
        with patch.object(capability_registry_module, "_MAX_CHILDREN", 2):
            snapshot = CapabilityRegistry(self.root).snapshot()

        skill_records = [
            record for record in snapshot.records
            if record.kind is CapabilityKind.SKILL
        ]
        self.assertEqual(len(skill_records), 2)
        self.assertIn("skill_child_limit", snapshot.issues)

    def test_candidate_collector_keeps_only_a_bounded_selection_window(self):
        self.assertTrue(hasattr(capability_registry_module, "_bounded_sorted"))

        class Candidate:
            live = 0
            peak = 0

            def __init__(self, value):
                self.value = value
                type(self).live += 1
                type(self).peak = max(type(self).peak, type(self).live)

            def __del__(self):
                type(self).live -= 1

        selected, count = capability_registry_module._bounded_sorted(
            (Candidate(value) for value in range(5000, -1, -1)),
            limit=3,
            key=lambda item: item.value,
        )

        self.assertEqual(count, 5001)
        self.assertEqual([item.value for item in selected], [0, 1, 2])
        self.assertLessEqual(Candidate.peak, 5)

    def test_tree_walker_rejects_excessive_directory_entries(self):
        self.assertTrue(hasattr(capability_registry_module, "_MAX_TREE_ENTRIES"))
        tree = self.root / "tree"
        (tree / "nested").mkdir(parents=True)
        (tree / "one.txt").write_text("one", encoding="utf-8")
        (tree / "nested" / "two.txt").write_text("two", encoding="utf-8")
        (tree / "nested" / "three.txt").write_text("three", encoding="utf-8")

        with patch.object(capability_registry_module, "_MAX_TREE_ENTRIES", 2):
            with self.assertRaises(CapabilityValidationError) as raised:
                capability_registry_module._hash_tree(tree)

        self.assertEqual(raised.exception.code, "tree_entry_limit")

        with patch.object(capability_registry_module, "_MAX_FILES", 2):
            with self.assertRaises(CapabilityValidationError) as raised:
                capability_registry_module._hash_tree(tree)

        self.assertEqual(raised.exception.code, "tree_file_limit")

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
