"""Regression tests for bounded memory export/import (Phase F transfer)."""

from __future__ import annotations

import shutil
import unittest
import uuid
from pathlib import Path

from app.memory_api import (
    MEMORY_API_MAX_IMPORT_ENTRIES,
    MemoryBackupFailedError,
    MemoryBackupNotFoundError,
    MemoryTransferRequestError,
    close_memory_search_indexes,
    create_memory_backup_for_api,
    export_memory_entries_for_api,
    import_memory_entries_for_api,
    list_memory_backups_for_api,
    restore_memory_backup_for_api,
)
from core.brain.context_compressor import MemoryEntry, MemoryStore, MemoryType


def _record(**overrides):
    record = {
        "type": "project",
        "title": "Transfer fixture",
        "content": "lossless transfer body",
        "tags": ["transfer"],
        "metadata": {"origin": "test"},
        "created_at": "2026-09-30T08:00:00",
        "last_accessed": "2026-09-30T09:00:00",
        "access_count": 3,
        "importance": 0.75,
        "token_count": 12,
        "compressed": False,
        "parent_id": None,
    }
    record.update(overrides)
    return record


class TestMemoryTransfer(unittest.TestCase):
    def setUp(self):
        self.source_dir = Path(f".test-memtransfer-{uuid.uuid4().hex[:8]}")
        self.target_dir = Path(f".test-memtransfer-{uuid.uuid4().hex[:8]}")
        for directory in (self.source_dir, self.target_dir):
            directory.mkdir(parents=True, exist_ok=True)
            self.addCleanup(shutil.rmtree, directory, True)
        self.addCleanup(close_memory_search_indexes)
        self.source = MemoryStore(memory_dir=str(self.source_dir))
        self.target = MemoryStore(memory_dir=str(self.target_dir))

    def _store_source_entry(self) -> MemoryEntry:
        entry = MemoryEntry.create(
            MemoryType.PROJECT,
            "Transfer fixture",
            "lossless transfer body",
            metadata={"origin": "test"},
            tags=["transfer"],
        )
        entry.id = "cust0m1d0001"
        entry.created_at = "2026-09-30T08:00:00"
        entry.last_accessed = "2026-09-30T09:00:00"
        entry.access_count = 3
        entry.importance = 0.75
        entry.token_count = 12
        entry.parent_id = "parent000001"
        self.source.store(entry)
        return entry

    def test_export_import_round_trip_is_lossless(self):
        self._store_source_entry()
        exported = export_memory_entries_for_api(self.source)
        self.assertEqual(exported["count"], 1)
        record = exported["entries"][0]
        self.assertEqual(record["id"], "cust0m1d0001")
        self.assertEqual(record["parent_id"], "parent000001")
        self.assertEqual(record["access_count"], 3)
        self.assertEqual(record["metadata"], {"origin": "test"})

        result = import_memory_entries_for_api(
            self.target, {"entries": exported["entries"]}
        )
        self.assertEqual(
            result,
            {
                "received": 1,
                "imported": 1,
                "skipped": 0,
                "rejected": 0,
                "errors": [],
            },
        )
        reexported = export_memory_entries_for_api(self.target)
        self.assertEqual(reexported["entries"], exported["entries"])

    def test_import_is_idempotent_across_repeated_requests(self):
        self._store_source_entry()
        payload = {"entries": export_memory_entries_for_api(self.source)["entries"]}
        first = import_memory_entries_for_api(self.target, payload)
        self.assertEqual(first["imported"], 1)
        second = import_memory_entries_for_api(self.target, payload)
        self.assertEqual(
            second,
            {
                "received": 1,
                "imported": 0,
                "skipped": 1,
                "rejected": 0,
                "errors": [],
            },
        )

    def test_import_dedupes_repeated_ids_inside_one_batch(self):
        result = import_memory_entries_for_api(
            self.target,
            {"entries": [_record(id="dup00000001"), _record(id="dup00000001")]},
        )
        self.assertEqual(result["imported"], 1)
        self.assertEqual(result["skipped"], 1)

    def test_import_computes_deterministic_ids_when_absent(self):
        result = import_memory_entries_for_api(
            self.target, {"entries": [_record()]}
        )
        self.assertEqual(result["imported"], 1)
        expected_id = MemoryEntry.create(
            MemoryType.PROJECT,
            "Transfer fixture",
            "lossless transfer body",
            metadata={"origin": "test"},
            tags=["transfer"],
        ).id
        exported = export_memory_entries_for_api(self.target)
        self.assertEqual(exported["entries"][0]["id"], expected_id)

    def test_import_rejects_invalid_records_without_aborting_batch(self):
        result = import_memory_entries_for_api(
            self.target,
            {
                "entries": [
                    _record(id="ok0000000001"),
                    _record(id="bad000000001", type="not-a-type"),
                    _record(id="bad000000002", title="   "),
                    _record(id="bad000000003", tags="not-a-list"),
                    _record(id="has space"),
                    "junk-record",
                ]
            },
        )
        self.assertEqual(result["received"], 6)
        self.assertEqual(result["imported"], 1)
        self.assertEqual(result["rejected"], 5)
        self.assertEqual(len(result["errors"]), 5)
        for message in result["errors"]:
            self.assertNotIn("lossless transfer body", message)

    def test_import_bounds_batch_size_and_payload_shape(self):
        with self.assertRaises(MemoryTransferRequestError):
            import_memory_entries_for_api(
                self.target,
                {
                    "entries": [
                        _record(id=f"bulk{position:09d}")
                        for position in range(MEMORY_API_MAX_IMPORT_ENTRIES + 1)
                    ]
                },
            )
        with self.assertRaises(MemoryTransferRequestError):
            import_memory_entries_for_api(self.target, ["not-an-object"])
        with self.assertRaises(MemoryTransferRequestError):
            import_memory_entries_for_api(self.target, {"other": []})

    def test_import_skips_existing_ids(self):
        self._store_source_entry()
        exported = export_memory_entries_for_api(self.source)
        result = import_memory_entries_for_api(
            self.source, {"entries": exported["entries"]}
        )
        self.assertEqual(result["imported"], 0)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["rejected"], 0)


class TestMemoryBackup(unittest.TestCase):
    def setUp(self):
        self.source_dir = Path(f".test-membackup-{uuid.uuid4().hex[:8]}")
        self.target_dir = Path(f".test-membackup-{uuid.uuid4().hex[:8]}")
        for directory in (self.source_dir, self.target_dir):
            directory.mkdir(parents=True, exist_ok=True)
            self.addCleanup(shutil.rmtree, directory, True)
        self.addCleanup(close_memory_search_indexes)
        self.store = MemoryStore(memory_dir=str(self.source_dir))
        self.target = MemoryStore(memory_dir=str(self.target_dir))
        entry = MemoryEntry.create(
            MemoryType.PROJECT,
            "Backup fixture",
            "verified backup body",
            tags=["backup"],
        )
        entry.id = "backup0000001"
        self.store.store(entry)

    def _backup_file(self, name: str) -> Path:
        return self.source_dir / "backups" / name

    def test_backup_and_restore_round_trip(self):
        manifest = create_memory_backup_for_api(self.store)
        self.assertEqual(manifest["entries"], 1)
        self.assertRegex(manifest["backup"], r"^backup-.*\.json$")
        self.assertTrue(self._backup_file(manifest["backup"]).is_file())

        inventory = list_memory_backups_for_api(self.store)
        self.assertEqual(len(inventory["backups"]), 1)
        self.assertTrue(inventory["backups"][0]["intact"])
        self.assertEqual(
            inventory["backups"][0]["payload_sha256"],
            manifest["payload_sha256"],
        )

        result = restore_memory_backup_for_api(
            self.store, {"backup": manifest["backup"]}
        )
        self.assertEqual(result["backup"], manifest["backup"])
        self.assertEqual(result["skipped"], 1)

        backups_for_target = self.target_dir / "backups"
        backups_for_target.mkdir(exist_ok=True)
        self._backup_file(manifest["backup"]).replace(
            backups_for_target / manifest["backup"]
        )
        migrated = restore_memory_backup_for_api(
            self.target, {"backup": manifest["backup"]}
        )
        self.assertEqual(migrated["imported"], 1)
        self.assertEqual(
            export_memory_entries_for_api(self.target)["entries"],
            export_memory_entries_for_api(self.store)["entries"],
        )

    def test_restore_detects_tampered_backup(self):
        manifest = create_memory_backup_for_api(self.store)
        path = self._backup_file(manifest["backup"])
        tampered = path.read_text(encoding="utf-8").replace(
            "Backup fixture", "Tampered fixture"
        )
        path.write_text(tampered, encoding="utf-8")
        with self.assertRaises(MemoryBackupFailedError):
            restore_memory_backup_for_api(self.store, {"backup": manifest["backup"]})
        inventory = list_memory_backups_for_api(self.store)
        self.assertFalse(inventory["backups"][0]["intact"])
        self.assertEqual(len(export_memory_entries_for_api(self.store)["entries"]), 1)

    def test_restore_validates_backup_names(self):
        create_memory_backup_for_api(self.store)
        for bad in ("../escape.json", "backup-20260930T120000-abc.json",
                    "backup-20260930T120000-ABCDEF01.json", "other.json"):
            with self.assertRaises(MemoryTransferRequestError):
                restore_memory_backup_for_api(self.store, {"backup": bad})
        with self.assertRaises(MemoryBackupNotFoundError):
            restore_memory_backup_for_api(
                self.store,
                {"backup": "backup-20260930T120000000000-00000000.json"},
            )
        with self.assertRaises(MemoryTransferRequestError):
            restore_memory_backup_for_api(self.store, ["not-an-object"])

    def test_retention_prunes_oldest_backups(self):
        first = create_memory_backup_for_api(self.store, max_retained=2)
        second = create_memory_backup_for_api(self.store, max_retained=2)
        third = create_memory_backup_for_api(self.store, max_retained=2)
        names = [
            item["name"] for item in list_memory_backups_for_api(self.store)["backups"]
        ]
        self.assertEqual(len(names), 2)
        self.assertIn(third["backup"], names)
        # The three backups can share one wall-clock second, so the pruned
        # victim is any of the two older ones, never the newest.
        self.assertEqual(len(first["pruned"]) + len(second["pruned"]), 0)
        self.assertEqual(len(third["pruned"]), 1)
        self.assertIn(third["pruned"][0], (first["backup"], second["backup"]))
        self.assertNotIn(third["backup"], third["pruned"])

    def test_backup_retention_bounds(self):
        with self.assertRaises(MemoryTransferRequestError):
            create_memory_backup_for_api(self.store, max_retained=0)
        with self.assertRaises(MemoryTransferRequestError):
            create_memory_backup_for_api(self.store, max_retained=65)

    def test_backup_of_empty_store_round_trips(self):
        empty = MemoryStore(memory_dir=str(self.target_dir / "empty"))
        manifest = create_memory_backup_for_api(empty)
        self.assertEqual(manifest["entries"], 0)
        result = restore_memory_backup_for_api(empty, {"backup": manifest["backup"]})
        self.assertEqual(result["received"], 0)
        self.assertEqual(result["imported"], 0)


if __name__ == "__main__":
    unittest.main()
