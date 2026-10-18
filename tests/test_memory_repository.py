"""Regression tests for the MemoryRepository port (Phase F convergence)."""

from __future__ import annotations

import shutil
import unittest
import uuid
from pathlib import Path

from core.brain.context_compressor import MemoryEntry, MemoryStore, MemoryType
from core.contracts.memory_repository import (
    MEMORY_REPOSITORY_PORT_ID,
    MEMORY_REPOSITORY_PORT_VERSION,
    MemoryRepository,
    check_memory_repository_conformance,
)


def _entry_factory(position: int) -> MemoryEntry:
    return MemoryEntry.create(
        MemoryType.PROJECT,
        f"Port fixture {position}",
        f"port conformance body {position}",
        tags=["port"],
    )


class TestMemoryRepositoryConformance(unittest.TestCase):
    def setUp(self):
        self.source_dir = Path(f".test-memoryrepo-{uuid.uuid4().hex[:8]}")
        self.source_dir.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, self.source_dir, True)
        self.store = MemoryStore(memory_dir=str(self.source_dir))

    def test_port_metadata_is_stable(self):
        self.assertEqual(MEMORY_REPOSITORY_PORT_ID, "memory-repository")
        self.assertEqual(MEMORY_REPOSITORY_PORT_VERSION, 2)

    def test_writable_store_satisfies_the_port(self):
        self.assertIsInstance(self.store, MemoryRepository)
        self.assertFalse(self.store.read_only)
        check_memory_repository_conformance(
            self.store,
            entry_factory=_entry_factory,
        )

    def test_read_only_store_satisfies_the_port(self):
        seed = _entry_factory(0)
        self.store.store(seed)
        reader = MemoryStore(memory_dir=str(self.source_dir), read_only=True)
        self.assertIsInstance(reader, MemoryRepository)
        self.assertTrue(reader.read_only)
        check_memory_repository_conformance(
            reader,
            entry_factory=_entry_factory,
        )
        self.assertEqual(len(reader.load(max_files=1)), 1)

    def test_writable_store_rejects_read_only_budgets(self):
        with self.assertRaises(ValueError):
            self.store.load(max_files=1)

    def test_checker_rejects_non_conforming_objects(self):
        class NotARepository:
            pass

        with self.assertRaises(AssertionError):
            check_memory_repository_conformance(
                NotARepository(),
                entry_factory=_entry_factory,
            )

    def test_checker_refuses_read_only_repository_that_writes(self):
        class PermissiveReadOnlyRepository:
            read_only = True
            memory_dir = Path(".")

            def __init__(self):
                self._saved = None

            def load(self, memory_type=None, **budgets):
                return [] if self._saved is None else [self._saved]

            def store(self, entry):
                self._saved = entry
                return "stored"

            def get_stats(self):
                return {"total": 0 if self._saved is None else 1}

        with self.assertRaises(AssertionError):
            check_memory_repository_conformance(
                PermissiveReadOnlyRepository(),
                entry_factory=_entry_factory,
            )


if __name__ == "__main__":
    unittest.main()
