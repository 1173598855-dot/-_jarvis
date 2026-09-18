"""
Context Compressor tests - Phase 11 memory system
Run: python3 tests/test_context_compressor.py
"""
import errno
import inspect
import multiprocessing
import os
import sys
import tempfile
import threading
import time
import unittest
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from core.brain import context_compressor as context_compressor_module
from core.brain.context_compressor import (
    _MEMORY_MERGE_CONTENT_MAX_CHARS,
    _MEMORY_MERGE_SEPARATOR,
    _MEMORY_TRUNCATION_MARKER,
    ContextCompressor,
    LLMCompressor,
    MemoryEntry,
    MemoryStore,
    MemoryType,
    SemanticCompressor,
    _base_title,
    _marked_title,
)


def _store_memory_entry_in_process(
    memory_dir,
    title,
    content,
    index_read,
    release_index_read,
):
    store = MemoryStore(memory_dir=memory_dir)
    entry = MemoryEntry.create(MemoryType.USER, title, content)
    original_read_index = MemoryStore._read_index_unlocked

    def delayed_read_index(instance):
        value = original_read_index(instance)
        if instance.index_file.name == "MEMORY.md":
            index_read.set()
            release_index_read.wait(timeout=5)
            time.sleep(0.02)
        return value

    with patch.object(MemoryStore, "_read_index_unlocked", delayed_read_index):
        store.store(entry)


class TestMemoryEntry(unittest.TestCase):
    def test_create_user(self):
        e = MemoryEntry.create(MemoryType.USER, "t1", "content", tags=["a"])
        self.assertEqual(e.type, MemoryType.USER)
        self.assertEqual(e.title, "t1")
        self.assertEqual(e.content, "content")
        self.assertIn("a", e.tags)
        self.assertFalse(e.compressed)

    def test_default_importance(self):
        """importance defaults to 0.5 per implementation"""
        e = MemoryEntry.create(MemoryType.USER, "t", "c")
        self.assertEqual(e.importance, 0.5)

    def test_estimate_tokens_short(self):
        t = MemoryEntry._estimate_tokens("hello")
        self.assertGreaterEqual(t, 1)

    def test_estimate_tokens_long(self):
        t = MemoryEntry._estimate_tokens("word " * 1000)
        self.assertGreater(t, 500)


class TestContextCompressor(unittest.TestCase):
    def setUp(self):
        self.cc = ContextCompressor(max_tokens=4000)

    def test_compress_short_no_summary(self):
        conv = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
        r = self.cc.compress(conv)
        self.assertIn("hi", r)
        self.assertNotIn("[摘要]", r)

    def test_compress_long_with_summary(self):
        conv = [{"role": "user", "content": f"msg {i}"} for i in range(20)]
        r = self.cc.compress(conv)
        self.assertIn("[摘要]", r)

    def test_summarize_returns_string(self):
        msgs = [{"role": "user", "content": "决定使用 TS 开发前端"}]
        s = self.cc._summarize(msgs)
        self.assertIsInstance(s, str)
        self.assertIn("决定", s)

    def test_format_conversation(self):
        conv = [{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}]
        r = self.cc._format_conversation(conv)
        self.assertIn("user", r)
        self.assertIn("q", r)


class TestSemanticCompressor(unittest.TestCase):
    def setUp(self):
        self.sc = SemanticCompressor(token_budget=4000)

    def test_compress_returns_list(self):
        entries = [MemoryEntry.create(MemoryType.USER, f"e{i}", f"c{i}") for i in range(5)]
        result, stats = self.sc.compress(entries)
        self.assertIsInstance(result, list)

    def test_compress_stats_keys(self):
        """Stats uses keys: total, kept, summarized, pruned, merged, tokens_saved, remaining"""
        entries = [MemoryEntry.create(MemoryType.USER, f"e{i}", f"c{i}") for i in range(5)]
        _, stats = self.sc.compress(entries)
        self.assertIn("total", stats)
        self.assertIn("kept", stats)
        self.assertIn("remaining", stats)
        self.assertEqual(stats["total"], 5)

    def test_is_expired_recent(self):
        from datetime import datetime, timedelta
        e = MemoryEntry.create(MemoryType.USER, "t", "c")
        e.created_at = (datetime.now() - timedelta(days=1)).isoformat()
        self.assertFalse(self.sc._is_expired(e))

    def test_truncate_entry(self):
        long_content = "x" * 2000
        e = MemoryEntry.create(MemoryType.USER, "t", long_content)
        result = self.sc._truncate(e, max_tokens=50)
        self.assertIsNotNone(result)

    def test_merge_duplicates(self):
        e1 = MemoryEntry.create(MemoryType.USER, "same", "a")
        e2 = MemoryEntry.create(MemoryType.USER, "same", "b")
        result = self.sc._merge_duplicates([e1, e2])
        self.assertIsInstance(result, list)


class TestMemoryStore(unittest.TestCase):
    """Each test uses tempfile.TemporaryDirectory to ensure clean state"""

    def test_store_creates_files(self):
        """store() creates MEMORY.md + entry file in memory_dir"""
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            e = MemoryEntry.create(MemoryType.USER, "t1", "c1", tags=["t"])
            p = store.store(e)
            self.assertTrue(Path(p).exists())
            # After store: MEMORY.md + 1 entry file = 2 md files
            md_files = list(Path(tmp).glob("*.md"))
            self.assertEqual(len(md_files), 2)

    def test_store_rejects_oversized_index_before_writing_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            limit = 32
            store.index_file.write_bytes(b"x" * (limit + 1))
            entry = MemoryEntry.create(MemoryType.USER, "oversized-index", "content")

            with patch.object(
                context_compressor_module,
                "_MEMORY_INDEX_MAX_BYTES",
                limit,
            ):
                with self.assertRaisesRegex(OSError, "memory index"):
                    store.store(entry)

            self.assertFalse(
                (Path(tmp) / f"{entry.type.value}_{entry.id}.md").exists()
            )

    def test_store_rejects_dangling_index_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory_dir = Path(tmp) / "memory"
            memory_dir.mkdir()
            index_file = memory_dir / "MEMORY.md"
            try:
                index_file.symlink_to(memory_dir / "missing-index.md")
            except (NotImplementedError, OSError) as error:
                self.skipTest(f"symlink creation is unavailable: {error}")

            with self.assertRaises(OSError):
                MemoryStore(memory_dir=str(memory_dir))

            self.assertTrue(index_file.is_symlink())

    def test_store_rejects_entry_symlink_without_overwriting_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            memory_dir = root / "memory"
            store = MemoryStore(memory_dir=str(memory_dir))
            external = root / "outside.md"
            external.write_text("keep this file", encoding="utf-8")
            entry = MemoryEntry.create(MemoryType.USER, "linked-entry", "new content")
            target = memory_dir / f"{entry.type.value}_{entry.id}.md"
            try:
                target.symlink_to(external)
            except (NotImplementedError, OSError) as error:
                self.skipTest(f"symlink creation is unavailable: {error}")

            with self.assertRaises(OSError):
                store.store(entry)

            self.assertTrue(target.is_symlink())
            self.assertEqual(external.read_text(encoding="utf-8"), "keep this file")

    def test_store_rejects_entry_link_added_after_target_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            memory_dir = root / "memory"
            store = MemoryStore(memory_dir=str(memory_dir))
            external = root / "outside.md"
            external.write_text("keep this file", encoding="utf-8")
            entry = MemoryEntry.create(MemoryType.USER, "raced-entry", "new content")
            target = memory_dir / f"{entry.type.value}_{entry.id}.md"
            real_validate = store._ensure_regular_entry_target

            def add_link_after_validation(candidate):
                expected_stat = real_validate(candidate)
                try:
                    os.link(external, candidate)
                except OSError as error:
                    self.skipTest(f"hard-link creation is unavailable: {error}")
                return expected_stat

            with (
                patch.object(
                    store,
                    "_ensure_regular_entry_target",
                    side_effect=add_link_after_validation,
                ),
                self.assertRaises(OSError),
            ):
                store.store(entry)

            self.assertEqual(external.read_text(encoding="utf-8"), "keep this file")
            self.assertTrue(target.exists())

    def test_store_rejects_index_link_added_after_validated_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            memory_dir = root / "memory"
            store = MemoryStore(memory_dir=str(memory_dir))
            external = root / "outside-index.md"
            external.write_text("keep this index", encoding="utf-8")
            entry = MemoryEntry.create(MemoryType.USER, "raced-index", "new content")
            real_read = store._read_index_unlocked

            def replace_index_after_read():
                content = real_read()
                store.index_file.unlink()
                try:
                    os.link(external, store.index_file)
                except OSError as error:
                    self.skipTest(f"hard-link creation is unavailable: {error}")
                return content

            with (
                patch.object(
                    store,
                    "_read_index_unlocked",
                    side_effect=replace_index_after_read,
                ),
                self.assertRaises(OSError),
            ):
                store.store(entry)

            self.assertEqual(external.read_text(encoding="utf-8"), "keep this index")

    def test_store_removes_temporary_entry_after_fsync_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory_dir = Path(tmp)
            store = MemoryStore(memory_dir=str(memory_dir))
            original_index = store.index_file.read_bytes()
            entry = MemoryEntry.create(MemoryType.USER, "failed-fsync", "content")
            target = memory_dir / f"{entry.type.value}_{entry.id}.md"

            with (
                patch.object(
                    context_compressor_module.os,
                    "fsync",
                    side_effect=OSError("injected fsync failure"),
                ),
                self.assertRaises(OSError),
            ):
                store.store(entry)

            self.assertFalse(target.exists())
            self.assertEqual(store.index_file.read_bytes(), original_index)
            self.assertEqual(list(memory_dir.glob(".*.tmp")), [])

    def test_atomic_write_removes_temporary_file_when_opened_stat_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            target = Path(tmp) / "probe.md"

            with (
                patch.object(
                    context_compressor_module.os,
                    "fstat",
                    side_effect=OSError("injected fstat failure"),
                ),
                self.assertRaises(OSError),
            ):
                store._atomic_write_regular_target(
                    target,
                    b"payload",
                    None,
                    label="probe",
                )

            self.assertFalse(target.exists())
            self.assertEqual(list(Path(tmp).glob(".*.tmp")), [])

    def test_atomic_write_removes_temporary_file_when_path_stat_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            target = Path(tmp) / "probe.md"
            real_lstat = context_compressor_module.os.lstat

            def fail_temporary_lstat(path):
                if Path(path).name.startswith(".probe.md."):
                    raise OSError("injected temporary lstat failure")
                return real_lstat(path)

            with (
                patch.object(
                    context_compressor_module.os,
                    "lstat",
                    side_effect=fail_temporary_lstat,
                ),
                self.assertRaises(OSError),
            ):
                store._atomic_write_regular_target(
                    target,
                    b"payload",
                    None,
                    label="probe",
                )

            self.assertFalse(target.exists())
            self.assertEqual(list(Path(tmp).glob(".*.tmp")), [])

    def test_atomic_write_cleanup_continues_after_descriptor_close_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            target = Path(tmp) / "probe.md"
            real_close = context_compressor_module.os.close
            close_calls = 0
            leaked_descriptor = None

            def fail_first_closes(descriptor):
                nonlocal close_calls, leaked_descriptor
                close_calls += 1
                if close_calls <= 2:
                    leaked_descriptor = descriptor
                    raise OSError("injected descriptor close failure")
                return real_close(descriptor)

            try:
                with (
                    patch.object(
                        context_compressor_module.os,
                        "close",
                        side_effect=fail_first_closes,
                    ),
                    self.assertRaises(OSError),
                ):
                    store._atomic_write_regular_target(
                        target,
                        b"payload",
                        None,
                        label="probe",
                    )
            finally:
                if leaked_descriptor is not None:
                    try:
                        real_close(leaked_descriptor)
                    except OSError:
                        pass

            self.assertFalse(target.exists())
            self.assertEqual(list(Path(tmp).glob(".*.tmp")), [])

    def test_store_restores_existing_entry_when_index_replace_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory_dir = Path(tmp)
            store = MemoryStore(memory_dir=str(memory_dir))
            entry = MemoryEntry.create(MemoryType.USER, "rollback", "original")
            target = Path(store.store(entry))
            original_entry = target.read_bytes()
            original_index = store.index_file.read_bytes()
            entry.content = "replacement"
            real_replace = context_compressor_module.os.replace

            def fail_index_replace(source, destination):
                if Path(destination) == store.index_file:
                    raise OSError("injected index replace failure")
                return real_replace(source, destination)

            with (
                patch.object(
                    context_compressor_module.os,
                    "replace",
                    side_effect=fail_index_replace,
                ),
                self.assertRaises(OSError),
            ):
                store.store(entry)

            self.assertEqual(target.read_bytes(), original_entry)
            self.assertEqual(store.index_file.read_bytes(), original_index)
            self.assertEqual(list(memory_dir.glob(".*.tmp")), [])

    def test_store_removes_new_entry_when_index_replace_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory_dir = Path(tmp)
            store = MemoryStore(memory_dir=str(memory_dir))
            original_index = store.index_file.read_bytes()
            entry = MemoryEntry.create(MemoryType.USER, "rollback-new", "content")
            target = memory_dir / f"{entry.type.value}_{entry.id}.md"
            real_replace = context_compressor_module.os.replace

            def fail_index_replace(source, destination):
                if Path(destination) == store.index_file:
                    raise OSError("injected index replace failure")
                return real_replace(source, destination)

            with (
                patch.object(
                    context_compressor_module.os,
                    "replace",
                    side_effect=fail_index_replace,
                ),
                self.assertRaises(OSError),
            ):
                store.store(entry)

            self.assertFalse(target.exists())
            self.assertEqual(store.index_file.read_bytes(), original_index)
            self.assertEqual(list(memory_dir.glob(".*.tmp")), [])

    def test_delete_probe_keeps_candidate_when_index_is_oversized(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            entry = MemoryEntry.create(
                MemoryType.PROJECT,
                ".test-local-integration-oversized-index",
                "temporary",
                metadata={"probe_cleanup_token": "secret"},
            )
            path = Path(store.store(entry))
            limit = 32
            store.index_file.write_bytes(b"x" * (limit + 1))

            with patch.object(
                context_compressor_module,
                "_MEMORY_INDEX_MAX_BYTES",
                limit,
            ):
                self.assertFalse(
                    store.delete_probe(MemoryType.PROJECT, entry.id, "secret")
                )

            self.assertTrue(path.exists())

    def test_delete_probe_restores_entry_when_index_replace_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            entry = MemoryEntry.create(
                MemoryType.PROJECT,
                ".test-local-integration-index-failure",
                "temporary",
                metadata={"probe_cleanup_token": "secret"},
            )
            path = Path(store.store(entry))
            original_entry = path.read_bytes()
            original_index = store.index_file.read_bytes()
            real_replace = context_compressor_module.os.replace

            def fail_index_replace(source, destination):
                if Path(destination) == store.index_file:
                    raise OSError("injected index replace failure")
                return real_replace(source, destination)

            with (
                patch.object(
                    context_compressor_module.os,
                    "replace",
                    side_effect=fail_index_replace,
                ),
                self.assertRaises(OSError),
            ):
                store.delete_probe(
                    MemoryType.PROJECT,
                    entry.id,
                    "secret",
                )

            self.assertEqual(path.read_bytes(), original_entry)
            self.assertEqual(store.index_file.read_bytes(), original_index)

    def test_index_accepts_exact_configured_byte_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            limit = 64
            index = ("# Memory Index\n" + "x" * (limit - len("# Memory Index\n"))).encode(
                "utf-8"
            )
            store.index_file.write_bytes(index)

            with patch.object(
                context_compressor_module,
                "_MEMORY_INDEX_MAX_BYTES",
                limit,
            ):
                self.assertEqual(store._read_index_unlocked(), index.decode("utf-8"))

    def test_index_rejects_growth_after_underreported_stat(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            limit = 64
            index = b"# Memory Index\n" + b"x" * (limit + 1)
            store.index_file.write_bytes(index)
            real_lstat = context_compressor_module.os.lstat
            real_fstat = context_compressor_module.os.fstat
            actual_stat = real_lstat(store.index_file)
            stat_values = list(actual_stat)
            stat_values[6] = limit
            underreported = os.stat_result(stat_values)
            fstat_calls = 0

            def fake_lstat(path):
                if Path(path) == store.index_file:
                    return underreported
                return real_lstat(path)

            def fake_fstat(descriptor):
                nonlocal fstat_calls
                fstat_calls += 1
                result = real_fstat(descriptor)
                return underreported if fstat_calls == 1 else result

            with (
                patch.object(context_compressor_module.os, "lstat", fake_lstat),
                patch.object(context_compressor_module.os, "fstat", fake_fstat),
                patch.object(
                    context_compressor_module,
                    "_MEMORY_INDEX_MAX_BYTES",
                    limit,
                ),
                patch.object(MemoryStore, "_is_reparse_point", return_value=False),
            ):
                with self.assertRaisesRegex(OSError, "memory index"):
                    store._read_index_unlocked()

    def test_read_only_store_does_not_create_missing_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory_dir = Path(tmp) / "missing"
            self.assertIn("read_only", inspect.signature(MemoryStore).parameters)

            store = MemoryStore(memory_dir=str(memory_dir), read_only=True)

            self.assertEqual(store.load(), [])
            self.assertFalse(memory_dir.exists())

    def test_writable_store_rejects_symlinked_memory_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory_dir = Path(tmp) / "memory"
            outside = Path(tmp) / "outside"
            outside.mkdir()
            try:
                os.symlink(outside, memory_dir, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("directory symlinks are unavailable")

            with self.assertRaisesRegex(OSError, "memory root"):
                MemoryStore(memory_dir=str(memory_dir))

    def test_read_only_load_bounds_scans_files_and_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory_dir = Path(tmp)
            (memory_dir / "MEMORY.md").write_text("# Memory Index\n", encoding="utf-8")
            payload = (
                "---\nname: Match\ntype: user\nimportance: 0.5\n---\n\nneedle"
            )
            for index in range(4):
                (memory_dir / f"user_{index}.md").write_bytes(payload.encode("utf-8"))
            oversized = memory_dir / "user_oversized.md"
            oversized.write_bytes(b"x" * 256)
            self.assertIn("read_only", inspect.signature(MemoryStore).parameters)
            store = MemoryStore(memory_dir=str(memory_dir), read_only=True)

            file_limited = store.load(
                max_directory_entries=10,
                max_files=2,
                max_file_bytes=1024,
                max_total_bytes=4096,
            )
            directory_limited = store.load(
                max_directory_entries=1,
                max_files=10,
                max_file_bytes=1024,
                max_total_bytes=4096,
            )
            byte_limited = store.load(
                max_directory_entries=10,
                max_files=10,
                max_file_bytes=128,
                max_total_bytes=len(payload.encode("utf-8")),
            )

            self.assertEqual(len(file_limited), 2)
            self.assertLessEqual(len(directory_limited), 1)
            self.assertEqual(len(byte_limited), 1)
            self.assertTrue(all(entry.title == "Match" for entry in byte_limited))

    def test_read_only_load_skips_invalid_metadata_and_keeps_valid_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory_dir = Path(tmp)
            invalid = "---\nname: Broken\ntype: invalid\n---\n\nneedle"
            valid = "---\nname: Valid\ntype: user\n---\n\nneedle"
            (memory_dir / "user_bad.md").write_bytes(invalid.encode("utf-8"))
            (memory_dir / "user_good.md").write_bytes(valid.encode("utf-8"))
            store = MemoryStore(memory_dir=str(memory_dir), read_only=True)

            try:
                entries = store.load(
                    max_directory_entries=10,
                    max_files=10,
                    max_file_bytes=1024,
                    max_total_bytes=4096,
                )
            except ValueError as error:
                self.fail(f"invalid read-only candidate was not skipped: {error}")

            self.assertEqual([entry.title for entry in entries], ["Valid"])

    def test_read_only_load_skips_descriptor_read_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory_dir = Path(tmp)
            payload = "---\nname: Valid\ntype: user\n---\n\nneedle"
            (memory_dir / "user_bad.md").write_text(payload, encoding="utf-8")
            (memory_dir / "user_good.md").write_text(payload, encoding="utf-8")
            store = MemoryStore(memory_dir=str(memory_dir), read_only=True)
            original_read = os.read
            read_attempts = 0

            def fail_first_read(descriptor, byte_count):
                nonlocal read_attempts
                read_attempts += 1
                if read_attempts == 1:
                    raise OSError("injected descriptor read failure")
                return original_read(descriptor, byte_count)

            try:
                with patch("core.brain.context_compressor.os.read", fail_first_read):
                    entries = store.load(
                        max_directory_entries=10,
                        max_files=10,
                        max_file_bytes=1024,
                        max_total_bytes=4096,
                    )
            except OSError as error:
                self.fail(f"descriptor read error was not isolated: {error}")

            self.assertEqual([entry.title for entry in entries], ["Valid"])

    def test_writable_load_skips_invalid_metadata_and_keeps_valid_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory_dir = Path(tmp)
            invalid = (
                "---\nname: Broken\ntype: user\n"
                "access_count: not-an-integer\n---\n\nneedle"
            )
            valid = "---\nname: Valid\ntype: user\n---\n\nneedle"
            (memory_dir / "user_bad.md").write_text(invalid, encoding="utf-8")
            (memory_dir / "user_good.md").write_text(valid, encoding="utf-8")
            store = MemoryStore(memory_dir=str(memory_dir))

            entries = store.load()

            self.assertEqual([entry.title for entry in entries], ["Valid"])

    def test_writable_load_accepts_exact_legacy_directory_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory_dir = Path(tmp)
            (memory_dir / "MEMORY.md").write_text(
                "# Memory Index\n", encoding="utf-8"
            )
            (memory_dir / "user_valid.md").write_text(
                "---\nname: Valid\ntype: user\n---\n\nkeep",
                encoding="utf-8",
            )
            store = MemoryStore(memory_dir=str(memory_dir))
            exact_budget = len(list(memory_dir.iterdir()))

            with patch.object(
                context_compressor_module,
                "_MEMORY_LEGACY_DIRECTORY_ENTRIES",
                exact_budget,
            ):
                entries = store.load()

            self.assertEqual([entry.title for entry in entries], ["Valid"])

    def test_writable_load_rejects_legacy_directory_overflow_without_partial_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory_dir = Path(tmp)
            (memory_dir / "MEMORY.md").write_text(
                "# Memory Index\n", encoding="utf-8"
            )
            for name in ("user_one.md", "user_two.md"):
                (memory_dir / name).write_text(
                    "---\nname: Valid\ntype: user\n---\n\nkeep",
                    encoding="utf-8",
                )
            store = MemoryStore(memory_dir=str(memory_dir))
            overflow_budget = len(list(memory_dir.iterdir())) - 1

            with patch.object(
                context_compressor_module,
                "_MEMORY_LEGACY_DIRECTORY_ENTRIES",
                overflow_budget,
            ):
                entries = store.load()

            self.assertEqual(entries, [])

    def test_bounded_legacy_scan_stops_at_first_overflow_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            limit = 2
            attempts = 0

            class GuardedScanner:
                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc_value, traceback):
                    return False

                def __iter__(self):
                    return self

                def __next__(self):
                    nonlocal attempts
                    attempts += 1
                    if attempts > limit + 1:
                        raise AssertionError("scanner advanced beyond first overflow")
                    return type(
                        "DirEntry",
                        (),
                        {"path": str(Path(tmp) / f"user_{attempts}.md")},
                    )()

            with (
                patch.object(
                    context_compressor_module,
                    "_MEMORY_LEGACY_DIRECTORY_ENTRIES",
                    limit,
                ),
                patch.object(
                    context_compressor_module.os,
                    "scandir",
                    return_value=GuardedScanner(),
                ),
            ):
                self.assertEqual(store._bounded_legacy_candidates(), [])

            self.assertEqual(attempts, limit + 1)

    def test_writable_load_rejects_external_symlink_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            memory_dir = root / "memory"
            store = MemoryStore(memory_dir=str(memory_dir))
            external = root / "outside.md"
            external.write_text(
                "---\nname: External\ntype: user\n---\n\noutside-secret",
                encoding="utf-8",
            )
            link = memory_dir / "user_external.md"
            try:
                link.symlink_to(external)
            except (NotImplementedError, OSError) as error:
                self.skipTest(f"symlink creation is unavailable: {error}")

            self.assertEqual(store.load(), [])

    def test_writable_load_skips_entry_over_the_size_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory_dir = Path(tmp)
            oversized = memory_dir / "user_oversized.md"
            oversized.write_text(
                "---\nname: Oversized\ntype: user\n---\n\n" + "x" * 128,
                encoding="utf-8",
            )
            valid = memory_dir / "user_valid.md"
            valid.write_text(
                "---\nname: Valid\ntype: user\n---\n\nkeep",
                encoding="utf-8",
            )
            store = MemoryStore(memory_dir=str(memory_dir))

            with patch.object(
                context_compressor_module,
                "_MEMORY_ENTRY_MAX_BYTES",
                64,
                create=True,
            ):
                entries = store.load()

            self.assertEqual([entry.title for entry in entries], ["Valid"])

    def test_delete_probe_keeps_entry_over_the_size_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            entry = MemoryEntry.create(
                MemoryType.PROJECT,
                ".test-local-integration-oversized-entry",
                "temporary",
                metadata={"probe_cleanup_token": "secret"},
            )
            path = Path(store.store(entry))
            path.write_text(
                "---\nname: .test-local-integration-oversized-entry\n"
                "type: project\nprobe_cleanup_token: secret\n---\n\n"
                + "x" * 128,
                encoding="utf-8",
            )

            with patch.object(
                context_compressor_module,
                "_MEMORY_ENTRY_MAX_BYTES",
                64,
                create=True,
            ):
                self.assertFalse(
                    store.delete_probe(MemoryType.PROJECT, entry.id, "secret")
                )

            self.assertTrue(path.exists())

    def test_writable_load_rejects_read_only_limits(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)

            with self.assertRaisesRegex(ValueError, "read-only"):
                store.load(max_files=1)

    def test_load_returns_correct_count(self):
        """Store 1 entry, load returns exactly 1 (MEMORY.md is excluded)"""
        uid = uuid.uuid4().hex[:6]
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            e = MemoryEntry.create(MemoryType.USER, f"t1_{uid}", "c1", tags=["t"])
            store.store(e)
            entries = store.load()
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0].title, f"t1_{uid}")

    def test_concurrent_same_title_store_keeps_one_index_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            entries = [
                MemoryEntry.create(MemoryType.USER, "shared-title", content)
                for content in ("first content", "second content")
            ]
            start = threading.Barrier(3)
            errors = []
            original_read_text = Path.read_text

            def delayed_read_text(path, *args, **kwargs):
                content = original_read_text(path, *args, **kwargs)
                if path == store.index_file:
                    time.sleep(0.02)
                return content

            def write(entry):
                try:
                    start.wait(timeout=5)
                    store.store(entry)
                except BaseException as error:
                    errors.append(error)

            workers = [threading.Thread(target=write, args=(entry,)) for entry in entries]
            with patch.object(Path, "read_text", delayed_read_text):
                for worker in workers:
                    worker.start()
                start.wait(timeout=5)
                for worker in workers:
                    worker.join(timeout=5)

            self.assertFalse(errors)
            self.assertTrue(all(not worker.is_alive() for worker in workers))
            index_rows = [
                line
                for line in store.index_file.read_text(encoding="utf-8").splitlines()
                if line.startswith("- [shared-title]")
            ]
            self.assertEqual(len(index_rows), 1)
            self.assertEqual(len(store.load()), 2)

    def test_store_replaces_index_row_by_filename_when_title_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            entry = MemoryEntry.create(
                MemoryType.USER,
                "original-index-title",
                "original content",
            )
            store.store(entry)

            entry.title = "updated-index-title"
            entry.content = "updated content"
            store.store(entry)

            rows = [
                line
                for line in store.index_file.read_text(encoding="utf-8").splitlines()
                if line.startswith("- [")
            ]
            self.assertEqual(rows, [
                f"- [updated-index-title](user_{entry.id}.md) -- updated content"
            ])

    def test_separate_instances_serialize_index_updates(self):
        with tempfile.TemporaryDirectory() as tmp:
            stores = [MemoryStore(memory_dir=tmp), MemoryStore(memory_dir=tmp)]
            entries = [
                MemoryEntry.create(MemoryType.USER, title, content)
                for title, content in (
                    ("shared-process-title-a", "first process content"),
                    ("shared-process-title-b", "second process content"),
                )
            ]
            start = threading.Barrier(3)
            errors = []
            index_read_count = 0
            index_read_count_lock = threading.Lock()
            first_index_read = threading.Event()
            second_index_read = threading.Event()
            release_first_index_read = threading.Event()
            original_read_index = MemoryStore._read_index_unlocked
            index_file = Path(tmp) / "MEMORY.md"

            def delayed_read_index(instance):
                nonlocal index_read_count
                content = original_read_index(instance)
                if instance.index_file == index_file:
                    with index_read_count_lock:
                        index_read_count += 1
                        is_first_read = index_read_count == 1
                    if is_first_read:
                        first_index_read.set()
                    else:
                        second_index_read.set()
                    release_first_index_read.wait(timeout=5)
                    time.sleep(0.02)
                return content

            def write(store, entry):
                try:
                    start.wait(timeout=5)
                    store.store(entry)
                except BaseException as error:
                    errors.append(error)

            workers = [
                threading.Thread(target=write, args=(store, entry))
                for store, entry in zip(stores, entries)
            ]
            with patch.object(
                MemoryStore,
                "_read_index_unlocked",
                delayed_read_index,
            ):
                for worker in workers:
                    worker.start()
                start.wait(timeout=5)
                self.assertTrue(first_index_read.wait(timeout=5))
                second_index_read.wait(timeout=0.1)
                release_first_index_read.set()
                for worker in workers:
                    worker.join(timeout=5)

            self.assertFalse(errors)
            self.assertTrue(all(not worker.is_alive() for worker in workers))
            self.assertEqual(index_read_count, 2)
            index_rows = [
                line
                for line in index_file.read_text(encoding="utf-8").splitlines()
                if line.startswith("- [shared-process-title-")
            ]
            self.assertEqual(len(index_rows), 2)
            self.assertEqual(len(stores[0].load()), 2)

    def test_spawned_processes_serialize_index_updates(self):
        with tempfile.TemporaryDirectory() as tmp:
            MemoryStore(memory_dir=tmp)
            context = multiprocessing.get_context("spawn")
            release_index_read = context.Event()
            first_index_read = context.Event()
            second_index_read = context.Event()
            processes = [
                context.Process(
                    target=_store_memory_entry_in_process,
                    args=(
                        tmp,
                        title,
                        content,
                        index_read,
                        release_index_read,
                    ),
                )
                for title, content, index_read in (
                    ("spawned-title-a", "first spawned content", first_index_read),
                    ("spawned-title-b", "second spawned content", second_index_read),
                )
            ]

            processes[0].start()
            self.assertTrue(first_index_read.wait(timeout=5))
            processes[1].start()
            second_index_read.wait(timeout=0.25)
            release_index_read.set()
            for process in processes:
                process.join(timeout=5)

            self.assertTrue(all(not process.is_alive() for process in processes))
            self.assertEqual([process.exitcode for process in processes], [0, 0])
            index_rows = [
                line
                for line in (Path(tmp) / "MEMORY.md").read_text(encoding="utf-8").splitlines()
                if line.startswith("- [spawned-title-")
            ]
            self.assertEqual(len(index_rows), 2)
            self.assertEqual(len(MemoryStore(memory_dir=tmp).load()), 2)

    def test_update_index_does_not_replace_substring_title(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            longer = MemoryEntry.create(MemoryType.USER, "foobar", "longer content")
            shorter = MemoryEntry.create(MemoryType.USER, "foo", "shorter content")

            store.store(longer)
            store.store(shorter)

            index_rows = [
                line
                for line in store.index_file.read_text(encoding="utf-8").splitlines()
                if line.startswith("- [")
            ]
            self.assertEqual(len(index_rows), 2)
            self.assertTrue(any(line.startswith("- [foobar](") for line in index_rows))
            self.assertTrue(any(line.startswith("- [foo](") for line in index_rows))

    def test_index_encodes_control_and_link_label_characters_in_one_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            title = "unsafe]\n- [forged"
            first = MemoryEntry.create(
                MemoryType.USER,
                title,
                "first summary\n- [content-forged](fake.md)\tend",
            )
            second = MemoryEntry.create(
                MemoryType.USER,
                title,
                "replacement summary\r\nnext",
            )

            store.store(first)
            store.store(second)

            index_rows = [
                line
                for line in store.index_file.read_text(encoding="utf-8").splitlines()
                if line.startswith("- [")
            ]
            self.assertEqual(len(index_rows), 1)
            self.assertIn(r"unsafe\]\n- \[forged", index_rows[0])
            self.assertIn(r"replacement summary\r\nnext", index_rows[0])
            self.assertNotIn("content-forged", index_rows[0])

    def test_store_load_round_trips_frontmatter_delimiters_and_newlines(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            entry = MemoryEntry.create(
                MemoryType.USER,
                "line one\n---\nline three",
                "body line one\n---\nbody line three",
            )

            store.store(entry)
            loaded = store.load()

            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0].title, entry.title)
            self.assertTrue(loaded[0].content.startswith(entry.content))

    def test_store_load_round_trips_every_memory_field_exactly(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            entry = MemoryEntry(
                id="roundtrip-id",
                type=MemoryType.PROJECT,
                title="A title with --- and [markers]",
                content="  body\n**metadata**: forged\n---\ntrailing spaces  ",
                metadata={
                    "nested": {"answer": 42, "enabled": True},
                    "probe_cleanup_token": "secret",
                },
                created_at="2026-08-29T10:11:12+08:00",
                last_accessed="2026-08-29T12:13:14+08:00",
                access_count=7,
                tags=["alpha", "comma,tag", ""],
                importance=0.875,
                token_count=42,
                compressed=True,
                parent_id="parent-id",
            )

            store.store(entry)
            loaded = store.load()

            self.assertEqual(loaded, [entry])
            raw = (Path(tmp) / "project_roundtrip-id.md").read_text(encoding="utf-8")
            self.assertIn("schema_version: 2", raw)

    def test_store_rejects_path_like_entry_id_before_writing_outside_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            memory_dir = root / "memory"
            store = MemoryStore(memory_dir=str(memory_dir))
            (memory_dir / "user_escape").mkdir()
            outside = root / "outside.md"
            entry = MemoryEntry.create(MemoryType.USER, "unsafe id", "content")
            entry.id = "escape/../../outside"

            with self.assertRaisesRegex(ValueError, "id"):
                store.store(entry)

            self.assertFalse(outside.exists())

    def test_store_rejects_values_that_cannot_round_trip_through_v2(self):
        invalid_fields = (
            ("type", "user"),
            ("title", 7),
            ("content", ["not", "text"]),
            ("metadata", {1: "integer key"}),
            ("metadata", {"tuple": ("changes", "type")}),
            ("tags", ["valid", 7]),
            ("created_at", None),
            ("last_accessed", None),
            ("access_count", True),
            ("access_count", -1),
            ("importance", float("inf")),
            ("token_count", True),
            ("token_count", -1),
            ("compressed", 0),
            ("parent_id", 7),
        )
        for field_name, invalid_value in invalid_fields:
            with self.subTest(field=field_name, value=invalid_value):
                with tempfile.TemporaryDirectory() as tmp:
                    store = MemoryStore(memory_dir=tmp)
                    entry = MemoryEntry.create(MemoryType.USER, "invalid", "content")
                    setattr(entry, field_name, invalid_value)

                    with self.assertRaises((TypeError, ValueError)):
                        store.store(entry)

                    self.assertEqual(
                        [path.name for path in Path(tmp).glob("*.md")],
                        ["MEMORY.md"],
                    )

    def test_store_rejects_oversized_v2_without_replacing_existing_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            entry = MemoryEntry.create(MemoryType.USER, "bounded", "original")
            path = Path(store.store(entry))
            original = path.read_bytes()
            entry.content = "x" * 1024

            with (
                patch.object(
                    context_compressor_module,
                    "_MEMORY_ENTRY_MAX_BYTES",
                    len(original) + 32,
                ),
                self.assertRaisesRegex(ValueError, "size limit"),
            ):
                store.store(entry)

            self.assertEqual(path.read_bytes(), original)

    def test_serialize_entry_uses_bounded_encoder_before_materializing_json(self):
        entry = MemoryEntry.create(
            MemoryType.USER,
            "bounded-json",
            "content",
            metadata={"payload": "x" * 4096},
        )

        with (
            patch.object(
                context_compressor_module,
                "_MEMORY_ENTRY_MAX_BYTES",
                256,
            ),
            patch.object(
                context_compressor_module.json,
                "dumps",
                side_effect=AssertionError("unbounded json.dumps called"),
            ),
            self.assertRaisesRegex(ValueError, "size limit"),
        ):
            MemoryStore._serialize_entry(entry)

    def test_store_rejects_oversized_index_update_before_entry_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            original_index = store.index_file.read_bytes()
            entry = MemoryEntry.create(
                MemoryType.USER,
                "title-that-makes-the-index-line-too-large",
                "content",
            )
            entry_path = Path(tmp) / f"user_{entry.id}.md"

            with (
                patch.object(
                    context_compressor_module,
                    "_MEMORY_INDEX_MAX_BYTES",
                    len(original_index) + 8,
                ),
                self.assertRaisesRegex(OSError, "memory index"),
            ):
                store.store(entry)

            self.assertFalse(entry_path.exists())
            self.assertEqual(store.index_file.read_bytes(), original_index)

    def test_load_rejects_v2_filename_outside_type_id_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            path = Path(tmp) / "arbitrary.md"
            path.write_text(
                "---\n"
                "schema_version: 2\n"
                "id: arbitrary\n"
                "name: Moved\n"
                "type: user\n"
                "metadata_json: {}\n"
                "tags_json: []\n"
                "created_at: now\n"
                "last_accessed: now\n"
                "access_count: 0\n"
                "importance: 0.5\n"
                "token_count: 1\n"
                "compressed: false\n"
                "parent_id: null\n"
                "probe_cleanup_token: \n"
                "---\n\nbody",
                encoding="utf-8",
            )

            self.assertEqual(store.load(), [])

    def test_load_reads_complete_legacy_footer_without_rewriting_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            path = Path(tmp) / "user_legacy-id.md"
            legacy = (
                "---\n"
                "name: Legacy record\n"
                "description: legacy summary\n"
                "type: user\n"
                "importance: 0.75\n"
                "token_count: 3\n"
                "compressed: False\n"
                "parent_id: \n"
                "probe_cleanup_token: \n"
                "---\n\n"
                "legacy body\n\n"
                '**metadata**: {"source":"fixture","nested":{"ok":true}}\n'
                "**tags**: legacy\n"
                "**created**: 2026-08-28T01:02:03\n"
                "**last_accessed**: 2026-08-29T04:05:06\n"
                "**access_count**: 2\n"
                "**importance**: 0.75\n"
            )
            path.write_text(legacy, encoding="utf-8")

            loaded = store.load()

            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0].id, "legacy-id")
            self.assertEqual(loaded[0].content, "legacy body")
            self.assertEqual(
                loaded[0].metadata,
                {"source": "fixture", "nested": {"ok": True}},
            )
            self.assertEqual(loaded[0].tags, ["legacy"])
            self.assertEqual(loaded[0].created_at, "2026-08-28T01:02:03")
            self.assertEqual(loaded[0].last_accessed, "2026-08-29T04:05:06")
            self.assertEqual(loaded[0].access_count, 2)
            self.assertEqual(path.read_text(encoding="utf-8"), legacy)

    def test_load_recovers_complete_legacy_footer_after_empty_body(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            path = Path(tmp) / "user_empty-legacy.md"
            path.write_text(
                "---\n"
                "name: Empty legacy\n"
                "type: user\n"
                "importance: 0.6\n"
                "token_count: 0\n"
                "compressed: False\n"
                "parent_id: \n"
                "probe_cleanup_token: \n"
                "---\n\n\n"
                '**metadata**: {"source":"legacy"}\n'
                "**tags**: empty-body\n"
                "**created**: 2026-08-28T01:02:03\n"
                "**last_accessed**: 2026-08-29T04:05:06\n"
                "**access_count**: 1\n"
                "**importance**: 0.60\n",
                encoding="utf-8",
            )

            loaded = store.load()

            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0].content, "")
            self.assertEqual(loaded[0].metadata, {"source": "legacy"})
            self.assertEqual(loaded[0].tags, ["empty-body"])

    def test_legacy_marker_like_body_is_not_silently_parsed_as_footer(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            path = Path(tmp) / "user_marker-id.md"
            body = "body\n\n**metadata**: this is prose\n**tags**: still prose\n"
            path.write_text(
                "---\nname: Marker\ntype: user\n---\n\n" + body,
                encoding="utf-8",
            )

            loaded = store.load()

            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0].content, body.strip())
            self.assertEqual(loaded[0].tags, [])

    def test_legacy_footer_marker_scan_does_not_repeat_full_reverse_search(self):
        class CountingText(str):
            rfind_calls = 0

            def rfind(self, *args):
                type(self).rfind_calls += 1
                return super().rfind(*args)

        body = CountingText("**metadata**: prose\n" * 2_000)
        result = MemoryStore._parse_legacy_footer(body, {})

        self.assertIsNone(result)
        self.assertLessEqual(CountingText.rfind_calls, 8)

    def test_legacy_footer_does_not_admit_nonfinite_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            path = Path(tmp) / "user_nonfinite-legacy.md"
            body = (
                "legacy body\n\n"
                '**metadata**: {"value":1e999}\n'
                "**tags**: legacy\n"
                "**created**: now\n"
                "**last_accessed**: now\n"
                "**access_count**: 0\n"
                "**importance**: 0.5\n"
            )
            path.write_text(
                "---\nname: Legacy\ntype: user\n---\n\n" + body,
                encoding="utf-8",
            )

            loaded = store.load()

            self.assertEqual(len(loaded), 1)
            self.assertNotIn("value", loaded[0].metadata)
            self.assertIn("**metadata**", loaded[0].content)

    def test_legacy_footer_does_not_leak_null_probe_cleanup_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            path = Path(tmp) / "user_null-token.md"
            path.write_text(
                "---\n"
                "name: Null token\n"
                "type: user\n"
                "probe_cleanup_token: secret\n"
                "---\n\n"
                '**metadata**: {"probe_cleanup_token":null}\n'
                "**tags**: fixture\n"
                "**created**: now\n"
                "**last_accessed**: now\n"
                "**access_count**: 0\n"
                "**importance**: 0.5\n",
                encoding="utf-8",
            )

            loaded = store.load()

            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0].metadata["probe_cleanup_token"], "secret")
            self.assertIn('"probe_cleanup_token":null', loaded[0].content)

    def test_malformed_v2_entry_is_skipped_without_hiding_valid_sibling(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            valid = MemoryEntry.create(MemoryType.USER, "valid-v2", "keep")
            store.store(valid)
            malformed = Path(tmp) / "user_malformed-v2.md"
            malformed.write_text(
                "---\n"
                "schema_version: 2\n"
                "id: malformed-v2\n"
                "name: Malformed\n"
                "type: user\n"
                "metadata_json: {\"ok\":true}\n"
                "tags_json: []\n"
                "created_at: now\n"
                "last_accessed: now\n"
                "access_count: 0\n"
                "importance: 0.5\n"
                "token_count: 1\n"
                "compressed: false\n"
                "parent_id: null\n"
                "probe_cleanup_token: \n"
                "not-a-field\n"
                "---\n\nignored",
                encoding="utf-8",
            )

            loaded = store.load()

            self.assertEqual([entry.title for entry in loaded], [valid.title])

    def test_v2_metadata_rejects_exponent_overflow_to_infinity(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            path = Path(tmp) / "user_nonfinite-json.md"
            path.write_text(
                "---\n"
                "schema_version: 2\n"
                "id: nonfinite-json\n"
                "name: Nonfinite\n"
                "type: user\n"
                'metadata_json: {"value":1e999}\n'
                "tags_json: []\n"
                "created_at: now\n"
                "last_accessed: now\n"
                "access_count: 0\n"
                "importance: 0.5\n"
                "token_count: 1\n"
                "compressed: false\n"
                "parent_id: null\n"
                "probe_cleanup_token: \n"
                "---\n\nbody",
                encoding="utf-8",
            )

            self.assertEqual(store.load(), [])

    def test_delete_probe_rejects_malformed_v2_before_unlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            entry = MemoryEntry.create(
                MemoryType.PROJECT,
                ".test-local-integration-malformed-v2",
                "temporary",
                metadata={"probe_cleanup_token": "secret"},
            )
            path = Path(store.store(entry))
            text = path.read_text(encoding="utf-8")
            path.write_text(text.replace('metadata_json: {"probe_cleanup_token":"secret"}',
                                         "metadata_json: not-json"), encoding="utf-8")

            self.assertFalse(
                store.delete_probe(MemoryType.PROJECT, entry.id, "secret")
            )
            self.assertTrue(path.exists())

    def test_delete_probe_rejects_legacy_declared_type_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            path = Path(tmp) / "project_cross-type.md"
            path.write_text(
                "---\n"
                "name: .test-local-integration-cross-type\n"
                "type: user\n"
                "probe_cleanup_token: secret\n"
                "---\n\nlegacy body",
                encoding="utf-8",
            )

            self.assertFalse(
                store.delete_probe(MemoryType.PROJECT, "cross-type", "secret")
            )
            self.assertTrue(path.exists())

    def test_delete_probe_keeps_replacement_after_validated_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            entry = MemoryEntry.create(
                MemoryType.PROJECT,
                ".test-local-integration-replaced-probe",
                "temporary",
                metadata={"probe_cleanup_token": "secret"},
            )
            path = Path(store.store(entry))
            replacement = Path(tmp) / "replacement.md"
            replacement.write_text("unverified replacement", encoding="utf-8")
            original_index = store.index_file.read_bytes()
            real_read = store._read_regular_candidate

            def replace_after_read(candidate, **kwargs):
                content = real_read(candidate, **kwargs)
                os.replace(replacement, candidate)
                return content

            with patch.object(
                store,
                "_read_regular_candidate",
                side_effect=replace_after_read,
            ):
                deleted = store.delete_probe(
                    MemoryType.PROJECT,
                    entry.id,
                    "secret",
                )

            self.assertFalse(deleted)
            self.assertEqual(path.read_text(encoding="utf-8"), "unverified replacement")
            self.assertEqual(store.index_file.read_bytes(), original_index)

    def test_store_load_round_trips_unicode_frontmatter_line_separators(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            title = "line one\u0085line two\u2028line three\u2029line four"
            entry = MemoryEntry.create(MemoryType.USER, title, "body")

            store.store(entry)
            loaded = store.load()

            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0].title, title)

    def test_load_filtered_by_type(self):
        """Filter by MemoryType.USER returns only USER entries"""
        uid = uuid.uuid4().hex[:6]
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            e1 = MemoryEntry.create(MemoryType.USER, f"u1_{uid}", "c1")
            e2 = MemoryEntry.create(MemoryType.PROJECT, f"p1_{uid}", "c2")
            store.store(e1)
            store.store(e2)
            user_entries = store.load(MemoryType.USER)
            self.assertEqual(len(user_entries), 1)
            self.assertEqual(user_entries[0].title, f"u1_{uid}")

    def test_delete_probe_removes_exact_entry_file_and_index_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            entry = MemoryEntry.create(
                MemoryType.PROJECT,
                ".test-local-integration-probe",
                "temporary",
                metadata={"probe_cleanup_token": "secret"},
            )
            path = Path(store.store(entry))

            deleted = store.delete_probe(
                MemoryType.PROJECT,
                entry.id,
                "secret",
            )

            self.assertTrue(deleted)
            self.assertFalse(path.exists())
            self.assertNotIn(entry.id, store.index_file.read_text(encoding="utf-8"))
            self.assertEqual(store.load(), [])

    def test_delete_probe_keeps_index_line_that_only_mentions_filename(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            entry = MemoryEntry.create(
                MemoryType.PROJECT,
                ".test-local-integration-index-substring",
                "temporary",
                metadata={"probe_cleanup_token": "secret"},
            )
            path = Path(store.store(entry))
            unrelated = (
                "- [unrelated](other.md) -- text mentions "
                f"({path.name})\n"
            )
            store.index_file.write_text(
                store.index_file.read_text(encoding="utf-8") + unrelated,
                encoding="utf-8",
            )

            self.assertTrue(
                store.delete_probe(MemoryType.PROJECT, entry.id, "secret")
            )

            self.assertIn(
                unrelated.strip(),
                store.index_file.read_text(encoding="utf-8"),
            )

    def test_delete_probe_parses_escaped_link_label_before_filename(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            entry = MemoryEntry.create(
                MemoryType.PROJECT,
                ".test-local-integration-title-](-marker",
                "temporary",
                metadata={"probe_cleanup_token": "secret"},
            )
            path = Path(store.store(entry))

            self.assertTrue(
                store.delete_probe(MemoryType.PROJECT, entry.id, "secret")
            )

            self.assertFalse(path.exists())
            self.assertNotIn(path.name, store.index_file.read_text(encoding="utf-8"))

    def test_delete_probe_rejects_invalid_entry_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)

            self.assertFalse(store.delete_probe(MemoryType.PROJECT, "../MEMORY", "secret"))

    def test_delete_probe_rejects_regular_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            entry = MemoryEntry.create(
                MemoryType.PROJECT,
                "real user memory",
                "keep this",
                metadata={"probe_cleanup_token": "secret"},
            )
            path = Path(store.store(entry))

            self.assertFalse(store.delete_probe(MemoryType.PROJECT, entry.id, "secret"))
            self.assertTrue(path.exists())

    def test_delete_probe_keeps_file_when_frontmatter_is_corrupt(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            path = store.memory_dir / "project_corrupt-probe.md"
            path.write_text(
                "---\n"
                "name: .test-local-integration-corrupt\n"
                "type: project\n"
                "probe_cleanup_token: \"bad\\q\"\n"
                "---\n\n"
                "temporary\n",
                encoding="utf-8",
            )

            self.assertFalse(
                store.delete_probe(MemoryType.PROJECT, "corrupt-probe", "secret")
            )
            self.assertTrue(path.exists())

    def test_delete_probe_rejects_external_symlink_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            memory_dir = root / "memory"
            store = MemoryStore(memory_dir=str(memory_dir))
            external = root / "outside.md"
            external.write_text(
                "---\n"
                "name: .test-local-integration-external\n"
                "type: project\n"
                "probe_cleanup_token: secret\n"
                "---\n\n"
                "outside\n",
                encoding="utf-8",
            )
            link = memory_dir / "project_external.md"
            try:
                link.symlink_to(external)
            except (NotImplementedError, OSError) as error:
                self.skipTest(f"symlink creation is unavailable: {error}")

            self.assertFalse(
                store.delete_probe(MemoryType.PROJECT, "external", "secret")
            )
            self.assertTrue(link.is_symlink())
            self.assertTrue(external.exists())

    def test_delete_probe_targets_one_memory_type_when_ids_collide(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            entries = [
                MemoryEntry.create(
                    memory_type,
                    ".test-local-integration-collision",
                    "same content",
                    metadata={"probe_cleanup_token": "secret"},
                )
                for memory_type in (MemoryType.USER, MemoryType.PROJECT)
            ]
            paths = [Path(store.store(entry)) for entry in entries]
            self.assertEqual(entries[0].id, entries[1].id)

            deleted = store.delete_probe(
                MemoryType.PROJECT,
                entries[1].id,
                "secret",
            )

            self.assertTrue(deleted)
            self.assertTrue(paths[0].exists())
            self.assertFalse(paths[1].exists())

    def test_index_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            e = MemoryEntry.create(MemoryType.USER, "idx", "content")
            store.store(e)
            self.assertTrue(store.index_file.exists())

    def test_consolidate_no_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            uid = uuid.uuid4().hex[:6]
            e1 = MemoryEntry.create(MemoryType.USER, f"s1_{uid}", "a")
            e2 = MemoryEntry.create(MemoryType.USER, f"s2_{uid}", "b")
            store.store(e1)
            store.store(e2)
            stats = store.consolidate()
            self.assertIn("merged", stats)

    def test_get_stats(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            e = MemoryEntry.create(MemoryType.USER, "st", "content")
            store.store(e)
            stats = store.get_stats()
            self.assertIn("total", stats)
            self.assertGreaterEqual(stats["total"], 1)


class TestMemoryStoreConcurrent(unittest.TestCase):
    """Thread safety test for MemoryStore"""

    def test_concurrent_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            errors = []

            def add_many(prefix):
                try:
                    for i in range(5):
                        e = MemoryEntry.create(MemoryType.USER, f"{prefix}_{i}", f"c{i}")
                        store.store(e)
                except Exception as ex:
                    errors.append(ex)

            threads = [threading.Thread(target=add_many, args=(f"t{j}",)) for j in range(3)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            self.assertEqual(len(errors), 0, f"Thread errors: {errors}")

class TestSemanticCompressorSummarize(unittest.TestCase):
    """_summarize(entry) returns MemoryEntry with summarized=True"""

    def setUp(self):
        self.sc = SemanticCompressor(token_budget=4000)

    def test_summarize_decision_content(self):
        """_summarize extracts decision sentences"""
        e = MemoryEntry.create(
            MemoryType.USER, "dec", "决定使用 TS 开发前端，因为类型安全",
            tags=["decision"]
        )
        result = self.sc._summarize(e)
        self.assertIsInstance(result, MemoryEntry)
        self.assertTrue(result.compressed)
        self.assertIn("[summary]", result.title)
        self.assertIn("summarized", result.metadata)
        self.assertIn("original_length", result.metadata)
        self.assertEqual(result.parent_id, e.id)

    def test_summarize_reduces_tokens(self):
        """_summarize should reduce token count vs original"""
        long_content = "这是一个很长的内容。" * 50
        e = MemoryEntry.create(MemoryType.USER, "long", long_content)
        original_tokens = e.token_count
        result = self.sc._summarize(e)
        self.assertLess(result.token_count, original_tokens)

    def test_summarize_no_keywords(self):
        """_summarize with no keyword sentences uses first 3 sentences"""
        e = MemoryEntry.create(
            MemoryType.USER, "plain", "第一句。第二句。第三句。第四句。"
        )
        result = self.sc._summarize(e)
        self.assertIn("[summary]", result.title)
        self.assertTrue(result.compressed)


class TestMemoryStoreDirectoryDurability(unittest.TestCase):
    """Renames and unlinks flush the containing directory entry."""

    def _make_probe(self, store):
        entry = MemoryEntry.create(
            MemoryType.PROJECT,
            ".test-local-integration-probe",
            "temporary",
            metadata={"probe_cleanup_token": "secret"},
        )
        return entry, Path(store.store(entry))

    def test_store_flushes_the_memory_directory_for_entry_and_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            entry = MemoryEntry.create(MemoryType.USER, "durable", "content")
            flushed = []

            with patch.object(
                context_compressor_module,
                "fsync_directory",
                side_effect=lambda directory: flushed.append(Path(directory)),
            ):
                store.store(entry)

            # Journal write, entry rename, index rename, journal removal.
            self.assertEqual(flushed, [Path(tmp)] * 4)

    def test_index_creation_flushes_the_memory_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            flushed = []

            with patch.object(
                context_compressor_module,
                "fsync_directory",
                side_effect=lambda directory: flushed.append(Path(directory)),
            ):
                MemoryStore(memory_dir=tmp)

            self.assertEqual(flushed, [Path(tmp)])
            self.assertTrue((Path(tmp) / "MEMORY.md").exists())

    def test_delete_probe_flushes_after_unlink_and_index_replace(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            entry, path = self._make_probe(store)
            flushed = []

            with patch.object(
                context_compressor_module,
                "fsync_directory",
                side_effect=lambda directory: flushed.append(Path(directory)),
            ):
                deleted = store.delete_probe(MemoryType.PROJECT, entry.id, "secret")

            self.assertTrue(deleted)
            self.assertFalse(path.exists())
            # Journal write, entry unlink, index rename, journal removal.
            self.assertEqual(flushed, [Path(tmp)] * 4)

    def test_store_fails_closed_when_the_directory_flush_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            entry = MemoryEntry.create(MemoryType.USER, "unflushable", "content")
            target = Path(tmp) / f"{entry.type.value}_{entry.id}.md"
            original_index = store.index_file.read_bytes()

            with (
                patch.object(
                    context_compressor_module,
                    "fsync_directory",
                    side_effect=OSError(errno.EIO, "device failure"),
                ),
                self.assertRaisesRegex(OSError, "cannot be written"),
            ):
                store.store(entry)

            self.assertFalse(target.exists())
            self.assertEqual(store.index_file.read_bytes(), original_index)
            self.assertEqual(list(Path(tmp).glob(".*.tmp")), [])

    def test_index_flush_failure_rolls_the_new_entry_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            entry = MemoryEntry.create(MemoryType.USER, "rollback", "content")
            target = Path(tmp) / f"{entry.type.value}_{entry.id}.md"
            original_index = store.index_file.read_bytes()
            calls = []

            def fail_on_the_index_flush(directory):
                calls.append(Path(directory))
                # 1: journal write, 2: entry rename, 3: index rename.
                if len(calls) > 2:
                    raise OSError(errno.EIO, "device failure")

            with (
                patch.object(
                    context_compressor_module,
                    "fsync_directory",
                    side_effect=fail_on_the_index_flush,
                ),
                self.assertRaises(OSError),
            ):
                store.store(entry)

            # The entry rolled back, but the index rename already landed without a
            # durable directory entry, so the intent record must survive.
            self.assertFalse(target.exists())
            self.assertTrue(store.journal_file.exists())
            self.assertEqual(list(Path(tmp).glob(".*.tmp")), [])

            # Recovery drops the row that no longer has an entry file.
            recovered = MemoryStore(memory_dir=tmp)
            self.assertFalse(recovered.journal_file.exists())
            self.assertEqual(
                recovered.index_file.read_bytes(),
                original_index.replace(b"\r\n", b"\n"),
            )

    def test_index_creation_flush_failure_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch.object(
                    context_compressor_module,
                    "fsync_directory",
                    side_effect=OSError(errno.EIO, "device failure"),
                ),
                self.assertRaisesRegex(OSError, "directory entry cannot be flushed"),
            ):
                MemoryStore(memory_dir=tmp)

    def test_read_only_store_never_flushes_a_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            MemoryStore(memory_dir=tmp)

            with patch.object(
                context_compressor_module,
                "fsync_directory",
                side_effect=AssertionError("read-only store must not flush"),
            ):
                read_only = MemoryStore(memory_dir=tmp, read_only=True)
                self.assertEqual(read_only.load(), [])

    def test_flush_helper_reports_the_failing_label(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)

            with (
                patch.object(
                    context_compressor_module,
                    "fsync_directory",
                    side_effect=OSError(errno.EIO, "device failure"),
                ),
                self.assertRaisesRegex(
                    OSError,
                    "probe label directory entry cannot be flushed",
                ),
            ):
                store._flush_parent_directory(
                    Path(tmp) / "entry.md",
                    label="probe label",
                )


class TestMemoryStoreJournal(unittest.TestCase):
    """The intent journal makes entry/index publication crash-consistent."""

    def _entry(self, title="journalled", content="content"):
        return MemoryEntry.create(MemoryType.USER, title, content)

    def _filename(self, entry):
        return f"{entry.type.value}_{entry.id}.md"

    def _write_journal(self, root, payload):
        journal = Path(root) / ".memory-journal"
        if isinstance(payload, bytes):
            journal.write_bytes(payload)
        else:
            journal.write_text(payload, encoding="utf-8")
        return journal

    def test_successful_store_leaves_no_journal(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            store.store(self._entry())

            self.assertFalse(store.journal_file.exists())

    def test_successful_delete_probe_leaves_no_journal(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            entry = MemoryEntry.create(
                MemoryType.PROJECT,
                ".test-local-integration-probe",
                "temporary",
                metadata={"probe_cleanup_token": "secret"},
            )
            store.store(entry)

            self.assertTrue(
                store.delete_probe(MemoryType.PROJECT, entry.id, "secret")
            )
            self.assertFalse(store.journal_file.exists())

    def test_journal_records_the_pending_store_filename(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            entry = self._entry()
            observed = {}
            real_write = store._atomic_write_regular_target

            def capture(filepath, payload, expected_stat, *, label):
                if label == "memory entry":
                    observed["journal"] = store.journal_file.read_bytes()
                return real_write(filepath, payload, expected_stat, label=label)

            with patch.object(
                store,
                "_atomic_write_regular_target",
                side_effect=capture,
            ):
                store.store(entry)

            self.assertEqual(
                observed["journal"],
                (
                    '{"schema_version":1,"operation":"store","filename":"'
                    + self._filename(entry)
                    + '"}'
                ).encode("utf-8") + b"\n",
            )

    def test_journal_records_the_pending_delete_filename(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            entry = MemoryEntry.create(
                MemoryType.PROJECT,
                ".test-local-integration-probe",
                "temporary",
                metadata={"probe_cleanup_token": "secret"},
            )
            store.store(entry)
            observed = {}
            real_write = store._atomic_write_regular_target

            def capture(filepath, payload, expected_stat, *, label):
                if label == "memory index":
                    observed["journal"] = store.journal_file.read_bytes()
                return real_write(filepath, payload, expected_stat, label=label)

            with patch.object(
                store,
                "_atomic_write_regular_target",
                side_effect=capture,
            ):
                store.delete_probe(MemoryType.PROJECT, entry.id, "secret")

            self.assertEqual(
                observed["journal"],
                (
                    '{"schema_version":1,"operation":"delete","filename":"'
                    + f"project_{entry.id}.md"
                    + '"}'
                ).encode("utf-8") + b"\n",
            )

    def test_recovery_adds_the_missing_index_row_for_a_stored_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            entry = self._entry("interrupted", "body text")
            filename = self._filename(entry)
            _, payload = store._serialize_entry(entry)
            (Path(tmp) / filename).write_bytes(payload)
            self._write_journal(
                tmp,
                '{"schema_version":1,"operation":"store","filename":"'
                + filename
                + '"}\n',
            )

            recovered = MemoryStore(memory_dir=tmp)

            index = recovered.index_file.read_text(encoding="utf-8")
            self.assertIn(f"- [interrupted]({filename}) -- body text", index)
            self.assertFalse(recovered.journal_file.exists())

    def test_recovery_removes_the_index_row_for_a_deleted_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            entry = self._entry("removed", "gone")
            filename = self._filename(entry)
            store.store(entry)
            (Path(tmp) / filename).unlink()
            self._write_journal(
                tmp,
                '{"schema_version":1,"operation":"delete","filename":"'
                + filename
                + '"}\n',
            )

            recovered = MemoryStore(memory_dir=tmp)

            self.assertNotIn(
                filename,
                recovered.index_file.read_text(encoding="utf-8"),
            )
            self.assertFalse(recovered.journal_file.exists())

    def test_recovery_replaces_a_stale_row_after_a_title_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            entry = self._entry("old title", "body")
            filename = self._filename(entry)
            store.store(entry)

            renamed = MemoryEntry(
                id=entry.id,
                type=entry.type,
                title="new title",
                content=entry.content,
                metadata=entry.metadata,
                created_at=entry.created_at,
                last_accessed=entry.last_accessed,
                access_count=entry.access_count,
                tags=entry.tags,
                importance=entry.importance,
                token_count=entry.token_count,
                compressed=entry.compressed,
                parent_id=entry.parent_id,
            )
            _, payload = store._serialize_entry(renamed)
            (Path(tmp) / filename).write_bytes(payload)
            self._write_journal(
                tmp,
                '{"schema_version":1,"operation":"store","filename":"'
                + filename
                + '"}\n',
            )

            recovered = MemoryStore(memory_dir=tmp)

            index = recovered.index_file.read_text(encoding="utf-8")
            self.assertIn(f"- [new title]({filename})", index)
            self.assertNotIn("old title", index)
            self.assertEqual(index.count(filename), 1)

    def test_recovery_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            entry = self._entry("idempotent", "body")
            filename = self._filename(entry)
            store.store(entry)
            expected = store.index_file.read_bytes()

            for _ in range(3):
                self._write_journal(
                    tmp,
                    '{"schema_version":1,"operation":"store","filename":"'
                    + filename
                    + '"}\n',
                )
                recovered = MemoryStore(memory_dir=tmp)
                self.assertFalse(recovered.journal_file.exists())
                self.assertEqual(recovered.index_file.read_bytes(), expected)

    def test_recovery_leaves_an_already_consistent_index_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            entry = self._entry("consistent", "body")
            filename = self._filename(entry)
            store.store(entry)
            before = store.index_file.stat()
            self._write_journal(
                tmp,
                '{"schema_version":1,"operation":"store","filename":"'
                + filename
                + '"}\n',
            )

            with patch.object(
                MemoryStore,
                "_atomic_write_regular_target",
                side_effect=AssertionError("index must not be rewritten"),
            ):
                recovered = MemoryStore(memory_dir=tmp)

            self.assertFalse(recovered.journal_file.exists())
            self.assertEqual(recovered.index_file.stat().st_size, before.st_size)

    def test_recovery_runs_before_the_next_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            interrupted = self._entry("interrupted", "first body")
            interrupted_name = self._filename(interrupted)
            _, payload = store._serialize_entry(interrupted)
            (Path(tmp) / interrupted_name).write_bytes(payload)
            self._write_journal(
                tmp,
                '{"schema_version":1,"operation":"store","filename":"'
                + interrupted_name
                + '"}\n',
            )

            follow_up = self._entry("follow up", "second body")
            store.store(follow_up)

            index = store.index_file.read_text(encoding="utf-8")
            self.assertIn(f"- [interrupted]({interrupted_name})", index)
            self.assertIn(f"- [follow up]({self._filename(follow_up)})", index)
            self.assertFalse(store.journal_file.exists())

    def test_recovery_keeps_the_index_for_an_unparseable_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            entry = self._entry("kept", "body")
            filename = self._filename(entry)
            store.store(entry)
            expected = store.index_file.read_bytes()
            (Path(tmp) / filename).write_text("not frontmatter", encoding="utf-8")
            self._write_journal(
                tmp,
                '{"schema_version":1,"operation":"store","filename":"'
                + filename
                + '"}\n',
            )

            recovered = MemoryStore(memory_dir=tmp)

            self.assertEqual(recovered.index_file.read_bytes(), expected)
            self.assertFalse(recovered.journal_file.exists())

    def test_malformed_journal_records_fail_closed(self):
        cases = {
            "not json": b"{",
            "not an object": b'["store"]',
            "missing field": b'{"schema_version":1,"operation":"store"}',
            "extra field": (
                b'{"schema_version":1,"operation":"store",'
                b'"filename":"user_a.md","extra":1}'
            ),
            "unknown schema": (
                b'{"schema_version":2,"operation":"store","filename":"user_a.md"}'
            ),
            "boolean schema": (
                b'{"schema_version":true,"operation":"store","filename":"user_a.md"}'
            ),
            "unknown operation": (
                b'{"schema_version":1,"operation":"purge","filename":"user_a.md"}'
            ),
            "duplicate key": (
                b'{"schema_version":1,"operation":"store",'
                b'"filename":"user_a.md","filename":"user_b.md"}'
            ),
            "absolute filename": (
                b'{"schema_version":1,"operation":"store",'
                b'"filename":"C:/other/user_a.md"}'
            ),
            "traversal filename": (
                b'{"schema_version":1,"operation":"store",'
                b'"filename":"../user_a.md"}'
            ),
            "unknown type prefix": (
                b'{"schema_version":1,"operation":"store","filename":"other_a.md"}'
            ),
            "missing separator": (
                b'{"schema_version":1,"operation":"store","filename":"user.md"}'
            ),
            "wrong suffix": (
                b'{"schema_version":1,"operation":"store","filename":"user_a.txt"}'
            ),
            "non-string filename": (
                b'{"schema_version":1,"operation":"store","filename":7}'
            ),
        }

        for label, payload in cases.items():
            with self.subTest(case=label):
                with tempfile.TemporaryDirectory() as tmp:
                    MemoryStore(memory_dir=tmp)
                    self._write_journal(tmp, payload)

                    with self.assertRaises(OSError):
                        MemoryStore(memory_dir=tmp)

    def test_oversized_journal_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            MemoryStore(memory_dir=tmp)
            self._write_journal(tmp, b" " * 4097)

            with self.assertRaisesRegex(OSError, "exceeds the size limit"):
                MemoryStore(memory_dir=tmp)

    def test_journal_directory_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            MemoryStore(memory_dir=tmp)
            (Path(tmp) / ".memory-journal").mkdir()

            with self.assertRaisesRegex(OSError, "must be a regular file"):
                MemoryStore(memory_dir=tmp)

    def test_uncleared_journal_blocks_a_new_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)

            with (
                patch.object(store, "_recover_journal_unlocked", return_value=None),
                patch.object(
                    store,
                    "_read_journal_unlocked",
                    return_value=None,
                ),
            ):
                self._write_journal(
                    tmp,
                    '{"schema_version":1,"operation":"store",'
                    '"filename":"user_a.md"}\n',
                )
                with self.assertRaisesRegex(OSError, "was not cleared"):
                    store.store(self._entry())

    def test_journal_write_rejects_unsupported_arguments(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)

            with self.assertRaisesRegex(OSError, "operation is not supported"):
                store._write_journal_unlocked("purge", "user_a.md")
            with self.assertRaisesRegex(OSError, "filename is not supported"):
                store._write_journal_unlocked("store", "../user_a.md")

    def test_recovery_purges_only_matching_stray_temporaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = MemoryStore(memory_dir=tmp)
            entry = self._entry("with strays", "body")
            filename = self._filename(entry)
            store.store(entry)

            token = "0" * 32
            strays = [
                root / f".{filename}.{token}.tmp",
                root / f".MEMORY.md.{token}.tmp",
                root / f"..memory-journal.{token}.tmp",
            ]
            keepers = [
                root / f".{filename}.{token}.bak",
                root / f".{filename}.{'z' * 32}.tmp",
                root / f".{filename}.{token[:31]}.tmp",
                root / f".unrelated_name.{token}.tmp",
                root / "regular.md",
            ]
            for candidate in strays + keepers:
                candidate.write_text("scratch", encoding="utf-8")

            self._write_journal(
                tmp,
                '{"schema_version":1,"operation":"store","filename":"'
                + filename
                + '"}\n',
            )

            MemoryStore(memory_dir=tmp)

            for stray in strays:
                self.assertFalse(stray.exists(), stray.name)
            for keeper in keepers:
                self.assertTrue(keeper.exists(), keeper.name)

    def test_read_only_store_never_recovers_or_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            MemoryStore(memory_dir=tmp)
            self._write_journal(tmp, b"{ not json")

            reader = MemoryStore(memory_dir=tmp, read_only=True)

            self.assertEqual(reader.load(), [])
            self.assertTrue((Path(tmp) / ".memory-journal").exists())

    def test_journal_is_never_loaded_as_an_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            store.store(self._entry("only entry", "body"))
            self._write_journal(
                tmp,
                '{"schema_version":1,"operation":"store",'
                '"filename":"user_a.md"}\n',
            )

            reader = MemoryStore(memory_dir=tmp, read_only=True)
            titles = [item.title for item in reader.load()]

            self.assertEqual(titles, ["only entry"])


class TestMemoryStoreConsolidateRemoval(unittest.TestCase):
    """consolidate() must actually apply the pruning and merging it reports."""

    def _entry_files(self, root):
        return sorted(
            path.name for path in Path(root).iterdir()
            if path.name.endswith(".md") and path.name != "MEMORY.md"
        )

    def _index_targets(self, store):
        targets = []
        for line in store.index_file.read_text(encoding="utf-8").splitlines():
            if not line.startswith("- ["):
                continue
            start = line.find("](")
            end = line.find(")", start)
            if start >= 0 and end > start:
                targets.append(line[start + 2:end])
        return sorted(targets)

    def _stale(self, store, title, content, importance=0.1):
        entry = MemoryEntry.create(
            MemoryType.USER, title, content, importance=importance
        )
        entry.last_accessed = (datetime.now() - timedelta(days=90)).isoformat()
        store.store(entry)
        return entry

    def test_pruned_entries_are_deleted_from_disk_and_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            stale = self._stale(store, "stale", "old content")
            keeper = MemoryEntry.create(
                MemoryType.USER, "keeper", "keep me", importance=0.9
            )
            store.store(keeper)

            stats = store.consolidate()

            self.assertEqual(stats["pruned"], 1)
            self.assertEqual(stats["removed"], 1)
            surviving = self._entry_files(tmp)
            self.assertEqual(surviving, [f"user_{keeper.id}.md"])
            self.assertNotIn(f"user_{stale.id}.md", surviving)
            self.assertEqual(self._index_targets(store), surviving)
            self.assertEqual([item.title for item in store.load()], ["keeper"])

    def test_merged_duplicate_is_deleted_from_disk_and_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            low = MemoryEntry.create(
                MemoryType.USER, "dup", "variant A", importance=0.9
            )
            low.access_count = 1
            store.store(low)
            high = MemoryEntry.create(
                MemoryType.USER, "dup", "variant B", importance=0.9
            )
            high.access_count = 7
            store.store(high)

            stats = store.consolidate()

            self.assertEqual(stats["merged"], 1)
            self.assertEqual(stats["removed"], 1)
            surviving = self._entry_files(tmp)
            self.assertEqual(len(surviving), 1)
            self.assertEqual(self._index_targets(store), surviving)
            self.assertEqual([item.title for item in store.load()], ["dup"])

    def test_summarized_entry_keeps_its_filename_and_is_not_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp, token_budget=1)
            entry = MemoryEntry.create(
                MemoryType.USER,
                "verbose",
                "decided one. decided two. decided three. decided four.",
                importance=0.4,
            )
            store.store(entry)

            stats = store.consolidate()

            self.assertEqual(stats["removed"], 0)
            self.assertEqual(self._entry_files(tmp), [f"user_{entry.id}.md"])
            self.assertEqual(self._index_targets(store), [f"user_{entry.id}.md"])

    def test_consolidate_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            self._stale(store, "stale", "old content")
            store.store(
                MemoryEntry.create(
                    MemoryType.USER, "keeper", "keep me", importance=0.9
                )
            )

            first = store.consolidate()
            files_after_first = self._entry_files(tmp)
            second = store.consolidate()

            self.assertEqual(first["removed"], 1)
            self.assertEqual(second["removed"], 0)
            self.assertEqual(self._entry_files(tmp), files_after_first)
            self.assertEqual(self._index_targets(store), files_after_first)

    def test_empty_store_consolidation_removes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)

            stats = store.consolidate()

            self.assertEqual(stats["total"], 0)
            self.assertEqual(stats["removed"], 0)
            self.assertEqual(self._entry_files(tmp), [])

    def test_unparseable_sibling_never_aborts_the_batch(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            self._stale(store, "stale", "old content")
            keeper = MemoryEntry.create(
                MemoryType.USER, "keeper", "keep me", importance=0.9
            )
            store.store(keeper)
            junk = Path(tmp) / "user_notanentry.md"
            junk.write_text("not frontmatter", encoding="utf-8")

            stats = store.consolidate()

            self.assertEqual(stats["removed"], 1)
            self.assertTrue(junk.exists())
            self.assertIn(f"user_{keeper.id}.md", self._entry_files(tmp))

    def test_delete_entry_rejects_non_entry_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)

            self.assertFalse(store._delete_entry_unlocked(store.index_file))
            self.assertFalse(
                store._delete_entry_unlocked(Path(tmp) / "user_missing.md")
            )
            self.assertTrue(store.index_file.exists())

    def test_interrupted_consolidation_leaves_no_orphan_index_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            for tag in ("a", "b", "c"):
                self._stale(store, f"stale-{tag}", f"old {tag}")
            keeper = MemoryEntry.create(
                MemoryType.USER, "keeper", "keep me", importance=0.9
            )
            store.store(keeper)

            real_publish = store._publish_entry_deletion_unlocked
            calls = []

            def fail_on_the_second_deletion(
                filepath, content, expected_index_stat, index_content
            ):
                calls.append(filepath.name)
                if len(calls) == 2:
                    # Journal and unlink land; the index rewrite never does.
                    store._write_journal_unlocked("delete", filepath.name)
                    filepath.unlink()
                    store._flush_parent_directory(
                        filepath, label="memory entry deletion"
                    )
                    raise OSError("simulated crash before the index write")
                return real_publish(
                    filepath, content, expected_index_stat, index_content
                )

            with patch.object(
                store,
                "_publish_entry_deletion_unlocked",
                side_effect=fail_on_the_second_deletion,
            ):
                with self.assertRaises(OSError):
                    store.consolidate()

            self.assertTrue(store.journal_file.exists())

            recovered = MemoryStore(memory_dir=tmp)
            files = self._entry_files(tmp)
            self.assertFalse(recovered.journal_file.exists())
            self.assertEqual(self._index_targets(recovered), files)

            recovered.consolidate()
            final_files = self._entry_files(tmp)
            self.assertEqual(final_files, [f"user_{keeper.id}.md"])
            self.assertEqual(self._index_targets(recovered), final_files)
            self.assertEqual(
                [item.title for item in recovered.load()], ["keeper"]
            )


class TestMemoryStoreEnsureIndex(unittest.TestCase):
    """_ensure_index() creates MEMORY.md if not present"""

    def test_ensure_index_creates_file_when_missing(self):
        """_ensure_index creates empty MEMORY.md when not present"""
        with tempfile.TemporaryDirectory() as tmp:
            _ = MemoryStore(memory_dir=tmp)
            idx = Path(tmp) / "MEMORY.md"
            self.assertTrue(idx.exists())
            content_text = idx.read_text(encoding="utf-8")
            expected = "# Memory Index" + chr(10)*2
            self.assertEqual(content_text, expected)

    def test_ensure_index_idempotent(self):
        """_ensure_index does not overwrite existing MEMORY.md"""
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            idx = Path(tmp) / "MEMORY.md"
            existing_content = "# Custom Index" + chr(10) + "-existing line" + chr(10)
            idx.write_text(existing_content, encoding="utf-8")
            store._ensure_index()
            self.assertEqual(idx.read_text(encoding="utf-8"), existing_content)


class TestMemoryStoreUpdateIndex(unittest.TestCase):
    """_update_index() updates or appends to MEMORY.md index"""

    def test_update_index_new_entry_appends(self):
        """_update_index appends new entry line when title not in index"""
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            e = MemoryEntry.create(MemoryType.USER, "new_title", "some content")
            store._update_index(e, "new_title.md")
            idx = Path(tmp) / "MEMORY.md"
            content_text = idx.read_text(encoding="utf-8")
            self.assertIn("new_title", content_text)
            self.assertIn("new_title.md", content_text)

    def test_update_index_existing_entry_replaces(self):
        """_update_index replaces line when title already in index"""
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            e1 = MemoryEntry.create(MemoryType.USER, "title_a", "content a")
            e2 = MemoryEntry.create(MemoryType.USER, "title_a", "content b updated")
            store.store(e1)
            store._update_index(e2, "title_a.md")
            idx = Path(tmp) / "MEMORY.md"
            lines = idx.read_text(encoding="utf-8").splitlines()
            title_a_lines = [ln for ln in lines if "title_a" in ln and ln.startswith("-")]
            self.assertEqual(len(title_a_lines), 1)
            self.assertIn("updated", title_a_lines[0])

# ============================================================
# TestMemoryStoreLosslessMerge
# ============================================================


class TestMemoryStoreLosslessMerge(unittest.TestCase):
    """Iteration 232: consolidation merges duplicate bodies instead of dropping one."""

    def _entry_files(self, memory_dir):
        return sorted(
            path.name
            for path in Path(memory_dir).glob("*.md")
            if path.name != "MEMORY.md"
        )

    def _index_targets(self, store):
        targets = []
        for line in store.index_file.read_text(encoding="utf-8").splitlines():
            if not line.startswith("- ["):
                continue
            start = line.find("](")
            end = line.find(")", start)
            if start >= 0 and end > start:
                targets.append(line[start + 2:end])
        return sorted(targets)

    def _duplicate_pair(self, store, high_body, low_body, title="dup"):
        high = MemoryEntry.create(MemoryType.USER, title, high_body, importance=0.9)
        high.access_count = 9
        low = MemoryEntry.create(MemoryType.USER, title, low_body, importance=0.9)
        low.access_count = 1
        store.store(high)
        store.store(low)
        return high, low

    def test_merge_keeps_both_bodies_in_the_surviving_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            high, low = self._duplicate_pair(store, "body of HIGH", "body of LOW")

            stats = store.consolidate()

            self.assertEqual(stats["merged"], 1)
            self.assertEqual(stats["removed"], 1)
            entries = store.load()
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0].id, high.id)
            self.assertIn("body of HIGH", entries[0].content)
            self.assertIn("body of LOW", entries[0].content)
            self.assertEqual(self._entry_files(tmp), [f"user_{high.id}.md"])
            self.assertNotIn(f"user_{low.id}.md", self._entry_files(tmp))

    def test_merge_records_absorbed_source_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            _high, low = self._duplicate_pair(store, "keep me", "absorb me")

            store.consolidate()

            entries = store.load()
            self.assertEqual(entries[0].metadata.get("merged_from"), [low.id])

    def test_repeated_consolidation_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            self._duplicate_pair(store, "first body", "second body")

            store.consolidate()
            first = store.load()[0].content
            second_stats = store.consolidate()
            second = store.load()[0].content

            self.assertEqual(first, second)
            self.assertEqual(second_stats["merged"], 0)
            self.assertEqual(second_stats["removed"], 0)
            self.assertEqual(second.count(_MEMORY_MERGE_SEPARATOR), 1)

    def test_merge_unions_tags_and_lifts_scalar_fields(self):
        compressor = SemanticCompressor(token_budget=1_000_000)
        high = MemoryEntry.create(MemoryType.USER, "same", "high body", importance=0.4)
        high.access_count = 6
        high.tags = ["shared", "high-only"]
        high.created_at = "2026-05-02T00:00:00"
        high.last_accessed = "2026-05-02T00:00:00"
        low = MemoryEntry.create(MemoryType.USER, "same", "low body", importance=0.8)
        low.access_count = 2
        low.tags = ["shared", "low-only"]
        low.created_at = "2026-05-01T00:00:00"
        low.last_accessed = "2026-05-09T00:00:00"

        merged = compressor._merge_duplicates([high, low])

        self.assertEqual(len(merged), 1)
        survivor = merged[0]
        self.assertEqual(survivor.id, high.id)
        self.assertEqual(survivor.tags, ["shared", "high-only", "low-only"])
        self.assertEqual(survivor.access_count, 6)
        self.assertAlmostEqual(survivor.importance, 0.8)
        self.assertEqual(survivor.created_at, "2026-05-01T00:00:00")
        self.assertEqual(survivor.last_accessed, "2026-05-09T00:00:00")
        self.assertGreater(survivor.token_count, 0)

    def test_duplicate_content_is_not_appended_twice(self):
        compressor = SemanticCompressor(token_budget=1_000_000)
        high = MemoryEntry.create(MemoryType.USER, "same", "identical body")
        high.access_count = 5
        low = MemoryEntry.create(MemoryType.USER, "same", "identical body")
        low.access_count = 1

        merged = compressor._merge_duplicates([high, low])

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].content, "identical body")
        self.assertEqual(merged[0].metadata.get("merged_from"), [low.id])

    def test_over_budget_merge_keeps_both_records(self):
        compressor = SemanticCompressor(token_budget=1_000_000)
        high = MemoryEntry.create(
            MemoryType.USER, "same", "A" * _MEMORY_MERGE_CONTENT_MAX_CHARS
        )
        high.access_count = 5
        low = MemoryEntry.create(MemoryType.USER, "same", "B" * 32)
        low.access_count = 1

        merged = compressor._merge_duplicates([high, low])

        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[0].content, "A" * _MEMORY_MERGE_CONTENT_MAX_CHARS)
        self.assertEqual(merged[1].content, "B" * 32)

    def test_over_budget_duplicates_are_not_deleted_from_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp, token_budget=1_000_000)
            high, low = self._duplicate_pair(
                store,
                "A" * _MEMORY_MERGE_CONTENT_MAX_CHARS,
                "B" * _MEMORY_MERGE_CONTENT_MAX_CHARS,
            )

            stats = store.consolidate()

            self.assertEqual(stats["merged"], 0)
            self.assertEqual(stats["removed"], 0)
            self.assertEqual(
                self._entry_files(tmp),
                sorted([f"user_{high.id}.md", f"user_{low.id}.md"]),
            )

    def test_three_duplicates_fold_into_one_survivor(self):
        compressor = SemanticCompressor(token_budget=1_000_000)
        entries = []
        for index, count in enumerate((2, 9, 4)):
            entry = MemoryEntry.create(MemoryType.USER, "same", f"body {index}")
            entry.access_count = count
            entries.append(entry)

        merged = compressor._merge_duplicates(entries)

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].id, entries[1].id)
        for index in range(3):
            self.assertIn(f"body {index}", merged[0].content)
        self.assertEqual(
            sorted(merged[0].metadata["merged_from"]),
            sorted([entries[0].id, entries[2].id]),
        )

    def test_externally_written_merged_from_is_tolerated(self):
        compressor = SemanticCompressor(token_budget=1_000_000)
        high = MemoryEntry.create(MemoryType.USER, "same", "high body")
        high.access_count = 5
        high.metadata["merged_from"] = "not-a-list"
        low = MemoryEntry.create(MemoryType.USER, "same", "low body")
        low.access_count = 1
        low.metadata["merged_from"] = [7, "legacy-id"]

        merged = compressor._merge_duplicates([high, low])

        self.assertEqual(merged[0].metadata["merged_from"], ["legacy-id", low.id])

    def test_distinct_titles_are_never_merged(self):
        compressor = SemanticCompressor(token_budget=1_000_000)
        first = MemoryEntry.create(MemoryType.USER, "alpha", "one")
        second = MemoryEntry.create(MemoryType.USER, "beta", "two")

        merged = compressor._merge_duplicates([first, second])

        self.assertEqual([entry.title for entry in merged], ["alpha", "beta"])
        self.assertNotIn("merged_from", merged[0].metadata)
        self.assertNotIn("merged_from", merged[1].metadata)

    def test_consolidation_stores_survivors_before_deleting_absorbed_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            high, low = self._duplicate_pair(store, "durable HIGH", "durable LOW")
            observed = []
            original_store = MemoryStore._store_unlocked
            original_delete = MemoryStore._delete_entry_unlocked

            def record_store(self, entry):
                observed.append(("store", f"{entry.type.value}_{entry.id}.md"))
                return original_store(self, entry)

            def record_delete(self, filepath):
                observed.append(("delete", filepath.name))
                return original_delete(self, filepath)

            with patch.object(MemoryStore, "_store_unlocked", record_store), \
                    patch.object(
                        MemoryStore, "_delete_entry_unlocked", record_delete
                    ):
                store.consolidate()

            self.assertIn(("store", f"user_{high.id}.md"), observed)
            self.assertIn(("delete", f"user_{low.id}.md"), observed)
            last_store = max(
                index for index, item in enumerate(observed) if item[0] == "store"
            )
            first_delete = min(
                index for index, item in enumerate(observed) if item[0] == "delete"
            )
            self.assertLess(last_store, first_delete)

    def test_survivor_content_is_durable_when_deletion_phase_crashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            high, low = self._duplicate_pair(store, "body HIGH", "body LOW")

            original_delete = MemoryStore._delete_entry_unlocked

            def delete_then_abort(self, filepath):
                original_delete(self, filepath)
                raise OSError("simulated crash right after one deletion")

            with patch.object(
                MemoryStore, "_delete_entry_unlocked", delete_then_abort
            ):
                with self.assertRaises(OSError):
                    store.consolidate()

            # The absorbed file is already gone, so its body only survives when
            # the merged survivor was published before the deletion.
            reopened = MemoryStore(memory_dir=tmp)
            surviving = reopened.load()
            self.assertEqual(self._entry_files(tmp), [f"user_{high.id}.md"])
            self.assertEqual(len(surviving), 1)
            self.assertIn("body HIGH", surviving[0].content)
            self.assertIn("body LOW", surviving[0].content)
            self.assertEqual(self._index_targets(reopened), [f"user_{high.id}.md"])

# ============================================================
# TestSemanticCompressorBoundedTransforms
# ============================================================


class TestSemanticCompressorBoundedTransforms(unittest.TestCase):
    """Iteration 233: truncation shrinks, and compression markers never stack."""

    def setUp(self):
        self.sc = SemanticCompressor(token_budget=4000)

    def _entry_files(self, memory_dir):
        return sorted(
            path.name
            for path in Path(memory_dir).glob("*.md")
            if path.name != "MEMORY.md"
        )

    def test_truncate_fits_the_token_budget(self):
        for body, budget in (
            ("X" * 5000, 500),
            ("中文内容" * 2000, 300),
            ("mixed {code} 内容 " * 400, 120),
            ("Y" * 60000, 500),
        ):
            with self.subTest(budget=budget, chars=len(body)):
                entry = MemoryEntry.create(MemoryType.USER, "t", body)
                result = self.sc._truncate(entry, max_tokens=budget)

                self.assertLessEqual(result.token_count, budget)
                self.assertEqual(
                    result.token_count,
                    MemoryEntry._estimate_tokens(result.content),
                )

    def test_truncate_actually_shrinks_the_body(self):
        body = "X" * 5000
        entry = MemoryEntry.create(MemoryType.USER, "t", body)

        result = self.sc._truncate(entry, max_tokens=500)

        self.assertLess(len(result.content), len(body))
        self.assertLess(result.token_count, entry.token_count)
        self.assertIn(_MEMORY_TRUNCATION_MARKER.strip(), result.content)

    def test_truncate_keeps_a_head_and_a_tail(self):
        body = "HEAD" + ("m" * 4000) + "TAIL"
        entry = MemoryEntry.create(MemoryType.USER, "t", body)

        result = self.sc._truncate(entry, max_tokens=500)

        self.assertTrue(result.content.startswith("HEAD"))
        self.assertTrue(result.content.endswith("TAIL"))

    def test_truncate_is_idempotent(self):
        entry = MemoryEntry.create(MemoryType.USER, "title", "W" * 6000)

        once = self.sc._truncate(entry, max_tokens=400)
        twice = self.sc._truncate(once, max_tokens=400)

        self.assertEqual(once.title, "title [truncated]")
        self.assertEqual(twice.title, "title [truncated]")
        self.assertEqual(once.content, twice.content)
        self.assertEqual(once.token_count, twice.token_count)

    def test_truncate_falls_back_to_the_marker_when_it_cannot_fit(self):
        entry = MemoryEntry.create(MemoryType.USER, "t", "Z" * 4000)

        result = self.sc._truncate(entry, max_tokens=1)

        self.assertEqual(result.content, _MEMORY_TRUNCATION_MARKER)
        self.assertLess(len(result.content), 4000)

    def test_truncate_leaves_a_short_entry_untouched(self):
        entry = MemoryEntry.create(MemoryType.USER, "t", "short")

        self.assertIs(self.sc._truncate(entry, max_tokens=500), entry)

    def test_summarize_marker_does_not_stack(self):
        entry = MemoryEntry.create(MemoryType.USER, "title", "决定采用方案A。其次是B。")

        once = self.sc._summarize(entry)
        twice = self.sc._summarize(once)

        self.assertEqual(once.title, "title [summary]")
        self.assertEqual(twice.title, "title [summary]")

    def test_mixed_markers_do_not_stack(self):
        summarized = self.sc._summarize(
            MemoryEntry.create(MemoryType.USER, "title", "决定采用方案A。" * 400)
        )
        self.assertEqual(summarized.title, "title [summary]")
        # Summarization already shortens the body, so re-truncation only runs
        # when the summary itself is still over the requested budget.
        oversized_summary = MemoryEntry.create(
            MemoryType.USER, summarized.title, "S" * 4000
        )

        retruncated = self.sc._truncate(oversized_summary, max_tokens=100)

        self.assertEqual(retruncated.title, "title [truncated]")
        self.assertLessEqual(retruncated.token_count, 100)

    def test_base_title_strips_repeated_markers(self):
        self.assertEqual(_base_title("x [truncated] [summary] [truncated]"), "x")
        self.assertEqual(_base_title("x [llm-summary]"), "x")
        self.assertEqual(_base_title("x"), "x")
        self.assertEqual(_base_title("x [summary] tail"), "x [summary] tail")

    def test_marked_title_replaces_an_existing_marker(self):
        self.assertEqual(_marked_title("x [summary]", " [truncated]"), "x [truncated]")
        self.assertEqual(_marked_title("x", " [summary]"), "x [summary]")

    def test_transformed_record_still_merges_with_its_twin(self):
        compressor = SemanticCompressor(token_budget=200)
        long_body = "决定采用方案A。" + ("填充 " * 400)
        verbose = MemoryEntry.create(
            MemoryType.PROJECT, "same", long_body, importance=0.5
        )
        verbose.access_count = 3
        brief = MemoryEntry.create(
            MemoryType.PROJECT, "same", "短正文", importance=0.9
        )
        brief.access_count = 1

        result, stats = compressor.compress([verbose, brief])

        self.assertEqual(stats["merged"], 1)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].title, "same")

    def test_merge_keeps_a_shared_marker(self):
        first = MemoryEntry.create(MemoryType.USER, "same [summary]", "one")
        first.access_count = 5
        second = MemoryEntry.create(MemoryType.USER, "same [summary]", "two")
        second.access_count = 1

        merged = self.sc._merge_duplicates([first, second])

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].title, "same [summary]")

    def test_compression_never_reports_negative_token_savings(self):
        compressor = SemanticCompressor(token_budget=200)
        entries = [
            MemoryEntry.create(MemoryType.USER, f"h{index}", "Q" * 4000, importance=0.9)
            for index in range(3)
        ]

        result, stats = compressor.compress(entries)

        self.assertGreater(stats["tokens_saved"], 0)
        for entry in result:
            self.assertLessEqual(entry.token_count, 500)

    def test_llm_compressor_markers_do_not_stack(self):
        compressor = LLMCompressor(ollama_manager=None)
        entry = MemoryEntry.create(
            MemoryType.USER, "title [summary]", "决定采用方案A。其次是B。"
        )

        result = compressor._heuristic_summarize(entry)

        self.assertEqual(result.title, "title [summary]")

    def test_llm_compressor_merges_across_markers(self):
        verbose = MemoryEntry.create(MemoryType.USER, "same [summary]", "one")
        verbose.access_count = 1
        plain = MemoryEntry.create(MemoryType.USER, "same", "two")
        plain.access_count = 7

        merged = LLMCompressor._merge_duplicates([verbose, plain])

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].id, plain.id)

    def test_repeated_consolidation_reaches_a_fixed_point(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp, token_budget=200)
            entry = MemoryEntry.create(
                MemoryType.PROJECT,
                "planning",
                "决定采用方案A。" + ("详细论述内容 " * 200),
                importance=0.8,
            )
            entry.access_count = 9
            store.store(entry)

            store.consolidate()
            first = store.load()
            self.assertEqual(first[0].title, "planning [truncated]")

            for _round in range(4):
                store.consolidate()

            final = store.load()
            self.assertEqual(len(final), 1)
            self.assertEqual(final[0].title, "planning [truncated]")
            self.assertEqual(final[0].content, first[0].content)
            self.assertEqual(final[0].token_count, first[0].token_count)
            self.assertEqual(self._entry_files(tmp), [f"project_{entry.id}.md"])


def run_all_tests():
    print("=" * 60)
    print("J.A.R.V.I.S. context_compressor tests - Iteration 30")
    print("=" * 60)

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for tc in [TestMemoryEntry, TestContextCompressor, TestSemanticCompressor,
               TestSemanticCompressorSummarize, TestMemoryStore,
               TestMemoryStoreEnsureIndex, TestMemoryStoreUpdateIndex,
               TestMemoryStoreConcurrent]:
        suite.addTests(loader.loadTestsFromTestCase(tc))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print()
    print("=" * 60)
    total = result.testsRun
    passed = total - len(result.failures) - len(result.errors)
    print(f"Results: {total} tests, {passed} passed, {len(result.failures)} failed, {len(result.errors)} errors")
    print("=" * 60)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(run_all_tests())
