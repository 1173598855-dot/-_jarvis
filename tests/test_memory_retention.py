"""Regression tests for entry-level memory retention (Phase F)."""

from __future__ import annotations

import shutil
import unittest
import uuid
from pathlib import Path

from app.memory_api import (
    MemoryTransferRequestError,
    close_memory_search_indexes,
    prune_memory_entries_for_api,
)
from core.brain.context_compressor import MemoryEntry, MemoryStore, MemoryType


class TestMemoryStoreDelete(unittest.TestCase):
    def setUp(self):
        self.td = Path(f".test-memretention-{uuid.uuid4().hex[:8]}")
        self.td.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, self.td, True)
        self.addCleanup(close_memory_search_indexes)
        self.store = MemoryStore(memory_dir=str(self.td))

    def _store(self, entry_id: str, **metadata) -> MemoryEntry:
        entry = MemoryEntry.create(
            MemoryType.PROJECT,
            f"Retention fixture {entry_id}",
            "retention body",
            metadata=dict(metadata),
        )
        entry.id = entry_id
        self.store.store(entry)
        return entry

    def test_delete_removes_a_stored_entry(self):
        entry = self._store("delete000001")
        self.assertTrue(self.store.delete(entry.type, entry.id))
        self.assertEqual(
            [item.id for item in self.store.load()],
            [],
        )
        self.assertFalse(self.store.delete(entry.type, entry.id))

    def test_delete_refuses_probe_entries(self):
        entry = self._store("probe000001", probe_cleanup_token="token-1")
        self.assertFalse(self.store.delete(entry.type, entry.id))
        self.assertEqual(
            [item.id for item in self.store.load()],
            ["probe000001"],
        )

    def test_delete_returns_false_for_unknown_or_mismatched(self):
        self._store("known000001")
        self.assertFalse(
            self.store.delete(MemoryType.PROJECT, "missing00001")
        )
        self.assertFalse(self.store.delete(MemoryType.USER, "known000001"))

    def test_read_only_store_refuses_delete(self):
        entry = self._store("readonly0001")
        reader = MemoryStore(memory_dir=str(self.td), read_only=True)
        with self.assertRaises(PermissionError):
            reader.delete(entry.type, entry.id)


class TestMemoryPrune(unittest.TestCase):
    def setUp(self):
        self.td = Path(f".test-memprune-{uuid.uuid4().hex[:8]}")
        self.td.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, self.td, True)
        self.addCleanup(close_memory_search_indexes)
        self.store = MemoryStore(memory_dir=str(self.td))
        self._store_entry("oldlow0000001", "Stale project", 0.2, "2020-01-01T00:00:00")
        self._store_entry("fresh00000001", "Fresh valuable", 0.9, "2099-01-01T00:00:00")
        self._store_entry("mid0000000001", "Mid project", 0.5, "2099-01-01T00:00:00")
        self._store_entry(
            "probe00000001",
            "Integration probe",
            0.1,
            "2020-01-01T00:00:00",
            probe_cleanup_token="token-1",
        )

    def _store_entry(
        self,
        entry_id: str,
        title: str,
        importance: float,
        last_accessed: str,
        **metadata,
    ) -> MemoryEntry:
        entry = MemoryEntry.create(
            MemoryType.PROJECT,
            title,
            f"body for {title}",
            metadata=dict(metadata),
        )
        entry.id = entry_id
        entry.importance = importance
        entry.last_accessed = last_accessed
        self.store.store(entry)
        return entry

    def _ids(self):
        return sorted(entry.id for entry in self.store.load())

    def test_dry_run_reports_candidates_without_deleting(self):
        result = prune_memory_entries_for_api(
            self.store, {"max_entries": 2, "dry_run": True}
        )
        self.assertEqual(result["evaluated"], 4)
        self.assertEqual(result["matched"], 1)
        self.assertEqual(len(result["candidates"]), 1)
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["pruned"], [])
        self.assertEqual(len(self._ids()), 4)

    def test_max_entries_keeps_the_most_valuable(self):
        result = prune_memory_entries_for_api(self.store, {"max_entries": 2})
        self.assertEqual(result["matched"], 1)
        self.assertEqual(result["pruned"], ["oldlow0000001"])
        self.assertEqual(
            self._ids(),
            ["fresh00000001", "mid0000000001", "probe00000001"],
        )

    def test_max_age_days_prunes_stale_entries(self):
        result = prune_memory_entries_for_api(self.store, {"max_age_days": 365})
        self.assertEqual(result["matched"], 1)
        self.assertEqual(result["pruned"], ["oldlow0000001"])
        self.assertNotIn("probe00000001", result["pruned"])
        self.assertEqual(
            self._ids(),
            ["fresh00000001", "mid0000000001", "probe00000001"],
        )

    def test_min_importance_prunes_lightweight_entries(self):
        result = prune_memory_entries_for_api(self.store, {"min_importance": 0.6})
        self.assertEqual(result["matched"], 2)
        self.assertEqual(
            sorted(result["pruned"]),
            ["mid0000000001", "oldlow0000001"],
        )
        self.assertEqual(self._ids(), ["fresh00000001", "probe00000001"])

    def test_unparseable_timestamps_are_kept(self):
        entry = self._store_entry(
            "brokents000001", "Broken timestamp", 0.1, "not-a-date"
        )
        result = prune_memory_entries_for_api(self.store, {"max_age_days": 365})
        self.assertNotIn("brokents000001", result["pruned"])
        self.assertIn(entry.id, self._ids())

    def test_policy_validation(self):
        for bad in (
            {},
            {"unknown_field": 1},
            {"max_entries": 0},
            {"max_entries": 8193},
            {"max_age_days": 0},
            {"max_age_days": 3651},
            {"min_importance": 1.5},
            {"min_importance": "high"},
            {"dry_run": "yes"},
            ["not-an-object"],
        ):
            with self.assertRaises(MemoryTransferRequestError):
                prune_memory_entries_for_api(self.store, bad)

    def test_per_request_cap_bounds_deletions(self):
        for position in range(67):
            self._store_entry(
                f"bulk{position:09d}",
                f"Bulk {position}",
                0.4,
                "2099-01-01T00:00:00",
            )
        # 70 manageable entries, keep 5 -> 65 victims -> 64 deletions fit
        # into the per-request budget and one victim waits for the next call.
        result = prune_memory_entries_for_api(self.store, {"max_entries": 5})
        self.assertEqual(result["matched"], 65)
        self.assertEqual(len(result["pruned"]), 64)
        self.assertEqual(result["failed"], [])
        kept = [item for item in self._ids() if item.startswith("bulk")]
        self.assertEqual(len(kept), 4)


if __name__ == "__main__":
    unittest.main()
