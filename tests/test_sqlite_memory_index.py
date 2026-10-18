"""Regression tests for the Phase F SQLite memory metadata index."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import threading
import unittest
import uuid
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

from adapters.ollama_embedding import OllamaEmbeddingProvider
from adapters.sqlite_memory_index import (
    INDEX_MAX_CONTENT_CHARS,
    INDEX_MAX_ENTRIES,
    INDEX_SCHEMA_VERSION,
    SqliteMemoryIndex,
    SqliteMemoryIndexError,
)
from app.memory_api import (
    MEMORY_API_MAX_SEARCH_RESULTS,
    MemorySearchRequestError,
    MemorySemanticUnavailableError,
    close_memory_search_indexes,
    search_memory_entries_for_api,
)
from core.brain.context_compressor import MemoryEntry, MemoryStore, MemoryType
from core.contracts.embedding_provider import (
    EMBEDDING_MAX_BATCH_TEXTS,
    EMBEDDING_MAX_DIMS,
    EMBEDDING_MAX_TEXT_CHARS,
    EmbeddingProvider,
    EmbeddingProviderError,
    validate_embedding_model_id,
    validate_embedding_vectors,
)
from core.contracts.memory_search import (
    MAX_MEMORY_QUERY_CHARS,
    MAX_MEMORY_SNIPPET_CHARS,
    memory_fulltext_terms,
    memory_matches,
    memory_query_terms,
    memory_score,
    memory_snippet_text,
    memory_source_ids,
)


@dataclass
class FakeEntry:
    """Duck-typed entry for adapter tests without the Markdown store."""

    id: str
    type: Any
    title: str
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = "2026-09-29T00:00:00"
    last_accessed: str = "2026-09-29T00:00:00"
    access_count: int = 0
    tags: List[str] = field(default_factory=list)
    importance: float = 0.5
    token_count: int = 8
    parent_id: str | None = None

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.content.encode("utf-8")).hexdigest()


def _fake_entry(entry_id: str, content: str = "body", **overrides: Any) -> FakeEntry:
    overrides.setdefault("title", f"Entry {entry_id}")
    return FakeEntry(id=entry_id, type=MemoryType.PROJECT, content=content, **overrides)


class TestSqliteMemoryIndex(unittest.TestCase):
    def setUp(self):
        self.td = Path(f".test-memidx-{uuid.uuid4().hex[:8]}")
        self.td.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, self.td, True)
        self.addCleanup(close_memory_search_indexes)

    def _open_index(self, name: str = "index.sqlite3", **kwargs) -> Any:
        index = SqliteMemoryIndex(self.td / name, **kwargs)
        self.addCleanup(index.close)
        return index

    def test_reconcile_indexes_entry_fields(self):
        index = self._open_index()
        entry = _fake_entry(
            "abc123",
            content="durable body",
            title="Indexed title",
            tags=["alpha"],
            parent_id="parent1",
        )
        stats = index.reconcile([entry])
        self.assertEqual(stats, {"entries": 1, "reconciled": 1})

        rows = index.fetch_entries()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.id, "abc123")
        self.assertEqual(row.memory_type, "project")
        self.assertEqual(row.title, "Indexed title")
        self.assertEqual(row.content, "durable body")
        self.assertEqual(row.tags, ("alpha",))
        self.assertEqual(row.parent_id, "parent1")
        self.assertEqual(row.access_count, 0)
        self.assertEqual(row.importance, 0.5)
        self.assertEqual(row.token_count, 8)

    def test_reconcile_is_idempotent_on_unchanged_entries(self):
        index = self._open_index()
        entries = [
            _fake_entry("bbb", content="second"),
            _fake_entry("aaa", content="first"),
        ]
        first = index.reconcile(entries)
        rows_first = index.fetch_entries()
        second = index.reconcile(entries)
        self.assertEqual(second, {"entries": 2, "reconciled": 0})
        self.assertEqual(index.fetch_entries(), rows_first)
        self.assertEqual([row.id for row in rows_first], ["aaa", "bbb"])
        self.assertEqual(first, {"entries": 2, "reconciled": 1})

    def test_reconcile_tracks_added_and_removed_entries(self):
        index = self._open_index()
        alpha = _fake_entry("alpha", content="alpha body")
        index.reconcile([alpha])
        beta = _fake_entry("beta", content="beta body")
        index.reconcile([alpha, beta])
        self.assertEqual([row.id for row in index.fetch_entries()], ["alpha", "beta"])
        index.reconcile([beta])
        self.assertEqual([row.id for row in index.fetch_entries()], ["beta"])

    def test_content_hash_tracks_content_changes(self):
        index = self._open_index()
        index.reconcile([_fake_entry("same", content="one body")])
        original = index.fetch_entries()[0].content_hash
        index.reconcile([_fake_entry("same", content="another body")])
        changed = index.fetch_entries()[0].content_hash
        self.assertNotEqual(original, changed)
        self.assertEqual(len(changed), 64)

    def test_over_budget_entry_fails_closed_without_partial_write(self):
        index = self._open_index()
        index.reconcile([_fake_entry("keeper", content="kept body")])
        oversized = _fake_entry("toobig", content="x" * (INDEX_MAX_CONTENT_CHARS + 1))
        with self.assertRaises(SqliteMemoryIndexError):
            index.reconcile([_fake_entry("keeper", content="kept body"), oversized])
        rows = index.fetch_entries()
        self.assertEqual([row.id for row in rows], ["keeper"])

    def test_over_budget_entry_count_fails_closed(self):
        index = self._open_index()
        entries = [
            _fake_entry(f"entry-{position:05d}", content="body")
            for position in range(INDEX_MAX_ENTRIES + 1)
        ]
        with self.assertRaises(SqliteMemoryIndexError):
            index.reconcile(entries)
        self.assertEqual(index.fetch_entries(), [])

    def test_duplicate_ids_fail_closed(self):
        index = self._open_index()
        with self.assertRaises(SqliteMemoryIndexError):
            index.reconcile([
                _fake_entry("dup", content="first"),
                _fake_entry("dup", content="second"),
            ])

    def test_schema_version_mismatch_fails_closed(self):
        db_path = self.td / "index.sqlite3"
        index = SqliteMemoryIndex(db_path)
        index.reconcile([_fake_entry("one")])
        index.close()
        connection = sqlite3.connect(str(db_path))
        with connection:
            connection.execute(
                "UPDATE index_meta SET value = '999' WHERE key = 'schema_version'"
            )
        connection.close()
        with self.assertRaises(SqliteMemoryIndexError):
            SqliteMemoryIndex(db_path)

    def test_read_only_mode_never_creates_or_writes(self):
        missing = self.td / "missing.sqlite3"
        with self.assertRaises(SqliteMemoryIndexError):
            SqliteMemoryIndex(missing, read_only=True)
        self.assertFalse(missing.exists())

        db_path = self.td / "index.sqlite3"
        index = SqliteMemoryIndex(db_path)
        index.reconcile([_fake_entry("one")])
        index.close()

        reader = SqliteMemoryIndex(db_path, read_only=True)
        self.assertEqual([row.id for row in reader.fetch_entries()], ["one"])
        with self.assertRaises(SqliteMemoryIndexError):
            reader.reconcile([_fake_entry("two")])
        self.assertEqual([row.id for row in reader.fetch_entries()], ["one"])
        reader.close()

    def test_corrupt_row_json_fails_closed(self):
        db_path = self.td / "index.sqlite3"
        index = SqliteMemoryIndex(db_path)
        index.reconcile([_fake_entry("one")])
        index.close()
        connection = sqlite3.connect(str(db_path))
        with connection:
            connection.execute(
                "UPDATE memory_entries SET tags_json = '{bad' WHERE entry_id = 'one'"
            )
        connection.close()
        reader = SqliteMemoryIndex(db_path, read_only=True)
        with self.assertRaises(SqliteMemoryIndexError):
            reader.fetch_entries()
        reader.close()

    def test_stats_reports_bounded_health(self):
        index = self._open_index()
        index.reconcile([_fake_entry("one"), _fake_entry("two")])
        stats = index.stats()
        self.assertEqual(stats["schema_version"], INDEX_SCHEMA_VERSION)
        self.assertEqual(stats["entries"], 2)
        self.assertIsNotNone(stats["fingerprint"])
        self.assertFalse(stats["read_only"])
        self.assertTrue(stats["fts5"])

    def test_version1_index_is_transparently_reset_to_schema_v2(self):
        db_path = self.td / "index.sqlite3"
        index = self._open_index()
        index.reconcile([_fake_entry("legacy")])
        index.close()
        connection = sqlite3.connect(str(db_path))
        with connection:
            connection.execute(
                "UPDATE index_meta SET value = '1' WHERE key = 'schema_version'"
            )
            connection.execute("DROP TABLE memory_fts")
        connection.close()

        upgraded = self._open_index()
        stats = upgraded.stats()
        self.assertEqual(stats["schema_version"], INDEX_SCHEMA_VERSION)
        self.assertEqual(stats["entries"], 0)
        self.assertIsNone(stats["fingerprint"])
        upgraded.reconcile([_fake_entry("fresh", content="rebuild body")])
        rows = upgraded.fetch_entries()
        self.assertEqual([row.id for row in rows], ["fresh"])
        hits = upgraded.search_fulltext(["rebuild"])
        self.assertEqual([row.id for row, _ in hits], ["fresh"])

    def test_fulltext_matches_cjk_and_ascii_with_bm25_order(self):
        index = self._open_index()
        index.reconcile([
            _fake_entry(
                "cjk",
                content="记忆系统负责长期检索",
                title="中文条目",
            ),
            _fake_entry(
                "ascii",
                content="the deploy pipeline ships the app",
                title="Deploy workflow",
                tags=["deploy"],
            ),
        ])
        hits = index.search_fulltext(["记忆系统"])
        self.assertEqual([row.id for row, _ in hits], ["cjk"])
        hits = index.search_fulltext(["DEPLOY"])
        self.assertEqual([row.id for row, _ in hits], ["ascii"])
        self.assertGreater(hits[0][1], 0.0)

    def test_fulltext_or_semantics_rank_multi_term_matches_first(self):
        index = self._open_index()
        index.reconcile([
            _fake_entry("both", content="deploy pipeline rollout plan"),
            _fake_entry("one", content="calm rollout notes"),
        ])
        hits = index.search_fulltext(["deploy", "rollout"])
        self.assertEqual([row.id for row, _ in hits], ["both", "one"])
        self.assertGreater(hits[0][1], hits[1][1])

    def test_fulltext_rejects_short_or_unsafe_terms(self):
        index = self._open_index()
        with self.assertRaises(SqliteMemoryIndexError):
            index.search_fulltext(["ab"])
        with self.assertRaises(SqliteMemoryIndexError):
            index.search_fulltext(['has"quote'])
        with self.assertRaises(SqliteMemoryIndexError):
            index.search_fulltext([123])
        self.assertEqual(index.search_fulltext([]), [])

    def test_fulltext_no_match_returns_empty(self):
        index = self._open_index()
        index.reconcile([_fake_entry("one", content="calm body")])
        self.assertEqual(index.search_fulltext(["nonexistent"]), [])

    def test_fulltext_reflects_reconcile_drift(self):
        index = self._open_index()
        index.reconcile([_fake_entry("one", content="deploy pipeline body")])
        self.assertEqual(
            [row.id for row, _ in index.search_fulltext(["deploy"])], ["one"]
        )
        index.reconcile([_fake_entry("two", content="calm body")])
        self.assertEqual(index.search_fulltext(["deploy"]), [])
        hits = index.search_fulltext(["calm"])
        self.assertEqual([row.id for row, _ in hits], ["two"])

    def test_vector_backlog_tracks_content_hash_coverage(self):
        index = self._open_index()
        alpha = _fake_entry("alpha", content="alpha body")
        beta = _fake_entry("beta", content="beta body")
        rows = [alpha, beta]
        index.reconcile(rows)
        self.assertEqual(
            [row.id for row in index.vector_backlog(rows, "embed-model")],
            ["alpha", "beta"],
        )
        index.store_vectors("embed-model", {
            "alpha": (alpha.content_hash, [1.0, 0.0]),
            "beta": (beta.content_hash, [0.0, 1.0]),
        })
        self.assertEqual(index.vector_backlog(rows, "embed-model"), [])
        stale_alpha = _fake_entry("alpha", content="changed body")
        index.reconcile([stale_alpha, beta])
        backlog = index.vector_backlog([stale_alpha, beta], "embed-model")
        self.assertEqual([row.id for row in backlog], ["alpha"])

    def test_reconcile_purges_orphaned_vectors(self):
        index = self._open_index()
        alpha = _fake_entry("alpha", content="alpha body")
        index.reconcile([alpha])
        index.store_vectors("embed-model", {"alpha": (alpha.content_hash, [1.0, 0.0])})
        self.assertEqual(index.stats()["vectors"], 1)
        index.reconcile([_fake_entry("beta", content="beta body")])
        self.assertEqual(index.stats()["vectors"], 0)

    def test_search_semantic_ranks_by_cosine_similarity(self):
        index = self._open_index()
        alpha = _fake_entry("alpha", content="alpha body")
        beta = _fake_entry("beta", content="beta body")
        index.reconcile([alpha, beta])
        index.store_vectors("embed-model", {
            "alpha": (alpha.content_hash, [1.0, 0.0]),
            "beta": (beta.content_hash, [0.0, 1.0]),
        })
        hits = index.search_semantic([0.9, 0.1], "embed-model")
        self.assertEqual([row.id for row, _ in hits], ["alpha", "beta"])
        self.assertGreater(hits[0][1], hits[1][1])
        self.assertGreater(hits[0][1], 0.9)
        self.assertLessEqual(hits[1][1], 0.111)

    def test_search_semantic_ignores_stale_vectors(self):
        index = self._open_index()
        alpha = _fake_entry("alpha", content="old body")
        index.reconcile([alpha])
        index.store_vectors("embed-model", {"alpha": (alpha.content_hash, [1.0, 0.0])})
        changed = _fake_entry("alpha", content="new body")
        index.reconcile([changed])
        self.assertEqual(index.search_semantic([1.0, 0.0], "embed-model"), [])

    def test_search_semantic_skips_dimension_mismatch(self):
        index = self._open_index()
        alpha = _fake_entry("alpha", content="alpha body")
        index.reconcile([alpha])
        index.store_vectors("embed-model", {"alpha": (alpha.content_hash, [1.0, 0.0, 0.0])})
        self.assertEqual(index.search_semantic([1.0, 0.0], "embed-model"), [])
        hits = index.search_semantic([1.0, 0.0, 0.0], "embed-model")
        self.assertEqual([row.id for row, _ in hits], ["alpha"])
        hits = index.search_semantic([0.0, 0.0, 1.0], "embed-model")
        self.assertEqual(len(hits), 1)

    def test_vector_model_isolation(self):
        index = self._open_index()
        alpha = _fake_entry("alpha", content="alpha body")
        index.reconcile([alpha])
        index.store_vectors("model-a", {"alpha": (alpha.content_hash, [1.0, 0.0])})
        self.assertEqual(index.vector_backlog([alpha], "model-a"), [])
        self.assertEqual(index.vector_backlog([alpha], "model-b"), [alpha])
        self.assertEqual(index.search_semantic([1.0, 0.0], "model-b"), [])

    def test_store_vectors_rejects_invalid_vectors(self):
        index = self._open_index()
        alpha = _fake_entry("alpha", content="alpha body")
        index.reconcile([alpha])
        with self.assertRaises(SqliteMemoryIndexError):
            index.store_vectors("embed-model", {"alpha": (alpha.content_hash, [0.0, 0.0])})
        with self.assertRaises(SqliteMemoryIndexError):
            index.store_vectors("embed-model", {"alpha": (alpha.content_hash, ["x"])})
        with self.assertRaises(SqliteMemoryIndexError):
            index.store_vectors("embed-model", {
                "alpha": (alpha.content_hash, [1.0, 0.0]),
                "beta": (alpha.content_hash, [1.0, 0.0, 0.0]),
            })
        with self.assertRaises((SqliteMemoryIndexError, EmbeddingProviderError)):
            index.store_vectors("", {"alpha": (alpha.content_hash, [1.0, 0.0])})

    def test_read_only_index_refuses_vector_writes(self):
        db_path = self.td / "index.sqlite3"
        writer = self._open_index()
        alpha = _fake_entry("alpha", content="alpha body")
        writer.reconcile([alpha])
        writer.close()
        reader = SqliteMemoryIndex(db_path, read_only=True)
        try:
            with self.assertRaises(SqliteMemoryIndexError):
                reader.store_vectors("embed-model", {"alpha": (alpha.content_hash, [1.0, 0.0])})
        finally:
            reader.close()

    def test_concurrent_reconcile_and_fetch_stay_consistent(self):
        import threading

        index = self._open_index()
        errors: List[Exception] = []

        def churn(position: int) -> None:
            try:
                for step in range(6):
                    entries = [
                        _fake_entry(f"shared-{inner}", content=f"body {inner}")
                        for inner in range(4)
                    ]
                    if step % 2 == 0:
                        entries.append(
                            _fake_entry(f"extra-{position}", content="transient")
                        )
                    index.reconcile(entries)
                    index.fetch_entries()
            except Exception as error:  # pragma: no cover - surfaced via list
                errors.append(error)

        threads = [threading.Thread(target=churn, args=(n,)) for n in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        rows = index.fetch_entries()
        self.assertEqual(len({row.id for row in rows}), len(rows))

    def test_rejects_invalid_row_shapes(self):
        index = self._open_index()
        with self.assertRaises(SqliteMemoryIndexError):
            index.reconcile([_fake_entry("")])
        with self.assertRaises(SqliteMemoryIndexError):
            index.reconcile([_fake_entry("ok", content=None)])
        with self.assertRaises(SqliteMemoryIndexError):
            index.reconcile([_fake_entry("ok", tags="not-a-list")])
        with self.assertRaises(SqliteMemoryIndexError):
            index.reconcile([_fake_entry("ok", access_count="many")])
        index.close()


class TestMemorySearchContract(unittest.TestCase):
    def test_query_terms_validation_and_normalization(self):
        with self.assertRaises(ValueError):
            memory_query_terms("   ")
        with self.assertRaises(ValueError):
            memory_query_terms("x" * (MAX_MEMORY_QUERY_CHARS + 1))
        with self.assertRaises(ValueError):
            memory_query_terms("!!!@@@###")
        terms = memory_query_terms("  Repo Scope repo 记忆  ")
        self.assertEqual(terms, ("repo", "scope", "记", "忆"))

    def test_score_matches_and_ordering_weights(self):
        @dataclass
        class Entry:
            id: str
            title: str
            content: str
            tags: List[str]

        title_hit = Entry("t", "Deploy guide", "unrelated body", [])
        tag_hit = Entry("g", "unrelated", "unrelated body", ["deploy"])
        body_hit = Entry("b", "unrelated", "the deploy pipeline", [])
        for entry in (title_hit, tag_hit, body_hit):
            self.assertTrue(memory_matches(entry, ("deploy",)))
        self.assertFalse(memory_matches(Entry("n", "calm", "quiet body", []), ("deploy",)))
        self.assertEqual(memory_score(title_hit, ("deploy",)), 5)
        self.assertEqual(memory_score(tag_hit, ("deploy",)), 3)
        self.assertEqual(memory_score(body_hit, ("deploy",)), 1)

    def test_snippet_alignment_and_bounds(self):
        content = "lead" * 200 + "needle" + "tail" * 200
        snippet = memory_snippet_text(content, ("needle",))
        self.assertIn("needle", snippet)
        self.assertLessEqual(len(snippet), MAX_MEMORY_SNIPPET_CHARS)
        head = memory_snippet_text("no match here", ("needle",))
        self.assertEqual(head, "no match here"[:MAX_MEMORY_SNIPPET_CHARS])

    def test_source_ids_are_bounded_and_deduplicated(self):
        @dataclass
        class Entry:
            id: str
            metadata: Dict[str, Any]
            parent_id: str | None

        entry = Entry(
            "self",
            metadata={
                "source_id": "src-1",
                "merged_from": ["src-1", "src-2", 5, "x" * 200, "src-3"],
            },
            parent_id="parent-1",
        )
        self.assertEqual(
            memory_source_ids(entry),
            ["src-1", "parent-1", "src-2", "src-3"],
        )

    def test_fulltext_terms_require_three_char_runs(self):
        with self.assertRaises(ValueError):
            memory_fulltext_terms("ab 记")
        self.assertEqual(
            memory_fulltext_terms("Deploy 记忆系统"),
            ("deploy", "记忆系统"),
        )
        self.assertEqual(
            memory_fulltext_terms("  REPO scope repo  "),
            ("repo", "scope"),
        )


class TestMemorySearchApi(unittest.TestCase):
    def setUp(self):
        self.td = Path(f".test-memsearch-{uuid.uuid4().hex[:8]}")
        self.td.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, self.td, True)
        self.addCleanup(close_memory_search_indexes)
        self.store = MemoryStore(memory_dir=str(self.td))
        self.store.store(MemoryEntry.create(
            MemoryType.PROJECT,
            "Deployment workflow",
            "The deploy pipeline ships the app",
            tags=["deploy"],
        ))
        self.store.store(MemoryEntry.create(
            MemoryType.USER,
            "Operator preferences",
            "Prefers concise reports",
            tags=["prefs"],
        ))

    def test_search_end_to_end_with_provenance(self):
        response = search_memory_entries_for_api(self.store, "deploy")
        self.assertEqual(response["query"], "deploy")
        self.assertEqual(response["count"], 1)
        result = response["results"][0]
        self.assertEqual(result["type"], "project")
        self.assertEqual(result["title"], "Deployment workflow")
        self.assertIn("deploy", result["snippet"].casefold())
        self.assertGreater(result["score"], 0)
        self.assertEqual(result["source_ids"], [])

    def test_search_ranks_title_matches_above_body_matches(self):
        self.store.store(MemoryEntry.create(
            MemoryType.PROJECT,
            "Operator notes",
            "the deploy pipeline for rollout",
            tags=["notes"],
        ))
        response = search_memory_entries_for_api(self.store, "deploy")
        self.assertEqual(response["count"], 2)
        self.assertEqual(response["results"][0]["title"], "Deployment workflow")
        self.assertEqual(
            [item["id"] for item in response["results"]],
            [
                item["id"]
                for item in sorted(
                    response["results"],
                    key=lambda item: (-item["score"], item["title"], item["id"]),
                )
            ],
        )

    def test_search_reconciles_new_entries_without_stale_results(self):
        response = search_memory_entries_for_api(self.store, "concise")
        self.assertEqual(response["count"], 1)
        self.store.store(MemoryEntry.create(
            MemoryType.REFERENCE,
            "Follow-up pointer",
            "a concise follow-up reference",
        ))
        response = search_memory_entries_for_api(self.store, "concise")
        self.assertEqual(response["count"], 2)
        self.assertTrue((self.td / "memory-index.sqlite3").is_file())

    def test_search_rejects_unbounded_requests(self):
        with self.assertRaises(MemorySearchRequestError):
            search_memory_entries_for_api(self.store, None)
        with self.assertRaises(MemorySearchRequestError):
            search_memory_entries_for_api(self.store, "")
        with self.assertRaises(MemorySearchRequestError):
            search_memory_entries_for_api(self.store, "   ")
        with self.assertRaises(MemorySearchRequestError):
            search_memory_entries_for_api(self.store, "query", limit=0)
        clamped = search_memory_entries_for_api(
            self.store, "deploy", limit=MEMORY_API_MAX_SEARCH_RESULTS * 10
        )
        self.assertLessEqual(clamped["count"], MEMORY_API_MAX_SEARCH_RESULTS)
        with self.assertRaises(MemorySearchRequestError):
            search_memory_entries_for_api(self.store, "x" * (MAX_MEMORY_QUERY_CHARS + 1))

    def test_search_fulltext_mode_end_to_end(self):
        response = search_memory_entries_for_api(
            self.store, "deploy pipeline", mode="fulltext"
        )
        self.assertEqual(response["mode"], "fulltext")
        self.assertEqual(response["count"], 1)
        result = response["results"][0]
        self.assertEqual(result["title"], "Deployment workflow")
        self.assertIsInstance(result["score"], float)
        self.assertGreater(result["score"], 0.0)
        self.assertIn("deploy", result["snippet"].casefold())

    def test_search_defaults_to_lexical_mode(self):
        response = search_memory_entries_for_api(self.store, "deploy")
        self.assertEqual(response["mode"], "lexical")
        self.assertIsInstance(response["results"][0]["score"], int)

    def test_search_rejects_invalid_mode_and_short_fulltext(self):
        with self.assertRaises(MemorySearchRequestError):
            search_memory_entries_for_api(self.store, "deploy", mode="hybrid")
        with self.assertRaises(MemorySemanticUnavailableError):
            search_memory_entries_for_api(self.store, "deploy", mode="semantic")
        with self.assertRaises(MemorySearchRequestError):
            search_memory_entries_for_api(self.store, "记", mode="fulltext")


class ScriptedEmbeddingProvider(EmbeddingProvider):
    """Deterministic fake provider mapping known texts to fixed vectors."""

    def __init__(self, mapping: Dict[str, List[float]], model_id: str = "scripted-embed"):
        self.mapping = mapping
        self._model_id = model_id
        self.calls: List[List[str]] = []

    @property
    def model_id(self) -> str:
        return self._model_id

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        self.calls.append(list(texts))
        vectors: List[List[float]] = []
        for text in texts:
            if text not in self.mapping:
                raise EmbeddingProviderError(f"unexpected text: {text[:32]}")
            vectors.append(list(self.mapping[text]))
        return vectors


class TestMemorySearchApiSemantic(unittest.TestCase):
    def setUp(self):
        self.td = Path(f".test-memsemantic-{uuid.uuid4().hex[:8]}")
        self.td.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, self.td, True)
        self.addCleanup(close_memory_search_indexes)
        self.store = MemoryStore(memory_dir=str(self.td))
        self.store.store(MemoryEntry.create(
            MemoryType.PROJECT,
            "Deployment workflow",
            "The deploy pipeline ships the app",
            tags=["deploy"],
        ))
        self.store.store(MemoryEntry.create(
            MemoryType.USER,
            "Operator preferences",
            "Prefers concise reports",
            tags=["prefs"],
        ))
        self.deploy_content = "The deploy pipeline ships the app"
        self.prefs_content = "Prefers concise reports"
        self.provider = ScriptedEmbeddingProvider({
            self.deploy_content: [1.0, 0.0, 0.0],
            self.prefs_content: [0.0, 1.0, 0.0],
            "deploy pipeline": [0.95, 0.05, 0.0],
        })

    def test_semantic_mode_ranks_by_similarity(self):
        response = search_memory_entries_for_api(
            self.store,
            "deploy pipeline",
            mode="semantic",
            embedding_provider=self.provider,
        )
        self.assertEqual(response["mode"], "semantic")
        self.assertEqual(response["count"], 2)
        self.assertEqual(response["results"][0]["title"], "Deployment workflow")
        self.assertIsInstance(response["results"][0]["score"], float)
        self.assertGreater(response["results"][0]["score"], 0.9)
        self.assertEqual(response["coverage"], {"vectors": 2, "entries": 2})
        # One batched backlog call plus the query embedding.
        self.assertEqual(len(self.provider.calls), 2)
        self.assertEqual(len(self.provider.calls[0]), 2)

    def test_semantic_mode_reuses_vectors_without_reembedding(self):
        search_memory_entries_for_api(
            self.store,
            "deploy pipeline",
            mode="semantic",
            embedding_provider=self.provider,
        )
        calls_after_first = len(self.provider.calls)
        response = search_memory_entries_for_api(
            self.store,
            "deploy pipeline",
            mode="semantic",
            embedding_provider=self.provider,
        )
        self.assertEqual(response["coverage"], {"vectors": 2, "entries": 2})
        self.assertEqual(len(self.provider.calls), calls_after_first + 1)
        self.assertEqual(self.provider.calls[-1], ["deploy pipeline"])

    def test_semantic_mode_reembeds_changed_content(self):
        search_memory_entries_for_api(
            self.store,
            "deploy pipeline",
            mode="semantic",
            embedding_provider=self.provider,
        )
        calls_after_first = len(self.provider.calls)
        self.store.store(MemoryEntry.create(
            MemoryType.REFERENCE,
            "Follow-up pointer",
            "A concise follow-up reference",
        ))
        self.provider.mapping["A concise follow-up reference"] = [0.0, 0.0, 1.0]
        response = search_memory_entries_for_api(
            self.store,
            "deploy pipeline",
            mode="semantic",
            embedding_provider=self.provider,
        )
        self.assertEqual(response["coverage"], {"vectors": 3, "entries": 3})
        self.assertEqual(len(self.provider.calls), calls_after_first + 2)

    def test_semantic_mode_requires_provider(self):
        with self.assertRaises(MemorySemanticUnavailableError):
            search_memory_entries_for_api(
                self.store, "deploy pipeline", mode="semantic"
            )

    def test_semantic_mode_wraps_provider_failures(self):
        class BrokenProvider(ScriptedEmbeddingProvider):
            def embed_texts(self, texts):
                raise EmbeddingProviderError("provider offline")

        with self.assertRaises(MemorySemanticUnavailableError):
            search_memory_entries_for_api(
                self.store,
                "deploy pipeline",
                mode="semantic",
                embedding_provider=BrokenProvider({}),
            )

    def test_semantic_mode_rejects_unbounded_queries(self):
        with self.assertRaises(MemorySearchRequestError):
            search_memory_entries_for_api(
                self.store,
                "   ",
                mode="semantic",
                embedding_provider=self.provider,
            )
        with self.assertRaises(MemorySearchRequestError):
            search_memory_entries_for_api(
                self.store,
                "x" * (MAX_MEMORY_QUERY_CHARS + 1),
                mode="semantic",
                embedding_provider=self.provider,
            )


class TestEmbeddingProviderContract(unittest.TestCase):
    def test_validate_batch_bounds(self):
        provider = ScriptedEmbeddingProvider({})
        with self.assertRaises(EmbeddingProviderError):
            provider.validate_batch("not-a-list")
        with self.assertRaises(EmbeddingProviderError):
            provider.validate_batch(["text"] * (EMBEDDING_MAX_BATCH_TEXTS + 1))
        with self.assertRaises(EmbeddingProviderError):
            provider.validate_batch([""])
        with self.assertRaises(EmbeddingProviderError):
            provider.validate_batch(["x" * (EMBEDDING_MAX_TEXT_CHARS + 1)])
        with self.assertRaises(EmbeddingProviderError):
            provider.validate_batch([123])
        self.assertEqual(provider.validate_batch(["ok"]), ["ok"])

    def test_validate_embedding_vectors_bounds(self):
        with self.assertRaises(EmbeddingProviderError):
            validate_embedding_vectors("nope")
        with self.assertRaises(EmbeddingProviderError):
            validate_embedding_vectors([])
        with self.assertRaises(EmbeddingProviderError):
            validate_embedding_vectors([[0.1, 0.2], [0.1]])
        with self.assertRaises(EmbeddingProviderError):
            validate_embedding_vectors([[0.0] * (EMBEDDING_MAX_DIMS + 1)])
        with self.assertRaises(EmbeddingProviderError):
            validate_embedding_vectors([[float("nan")]])
        with self.assertRaises(EmbeddingProviderError):
            validate_embedding_vectors([[True, False]])
        self.assertEqual(
            validate_embedding_vectors([[0.1, 0.2], [1, 2]]),
            [[0.1, 0.2], [1, 2]],
        )

    def test_validate_model_id_bounds(self):
        with self.assertRaises(EmbeddingProviderError):
            validate_embedding_model_id("")
        with self.assertRaises(EmbeddingProviderError):
            validate_embedding_model_id("x" * 129)
        with self.assertRaises(EmbeddingProviderError):
            validate_embedding_model_id("has space")
        self.assertEqual(
            validate_embedding_model_id("nomic-embed-text"),
            "nomic-embed-text",
        )


class _EmbeddingFixtureHandler(BaseHTTPRequestHandler):
    behavior = "ok"

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        if self.behavior == "http-error":
            self.send_response(500)
            self.end_headers()
            return
        if self.behavior == "bad-json":
            payload = b"{not json"
        elif self.behavior == "count-mismatch":
            payload = json.dumps({"embeddings": [[0.1, 0.2]]}).encode("utf-8")
        else:
            payload = json.dumps({
                "embeddings": [[0.1, 0.2], [0.3, 0.4]],
            }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format, *args):
        return


class TestOllamaEmbeddingProvider(unittest.TestCase):
    def setUp(self):
        self.server = HTTPServer(("127.0.0.1", 0), _EmbeddingFixtureHandler)
        self.behavior = "ok"
        _EmbeddingFixtureHandler.behavior = "ok"

        def serve():
            self.server.serve_forever()

        self.thread = threading.Thread(target=serve, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def test_embed_texts_success(self):
        provider = OllamaEmbeddingProvider(
            "nomic-embed-text", base_url=self.base_url
        )
        vectors = provider.embed_texts(["one", "two"])
        self.assertEqual(len(vectors), 2)
        self.assertEqual(vectors[0], [0.1, 0.2])
        self.assertEqual(provider.model_id, "nomic-embed-text")

    def test_count_mismatch_is_rejected(self):
        _EmbeddingFixtureHandler.behavior = "count-mismatch"
        provider = OllamaEmbeddingProvider(
            "nomic-embed-text", base_url=self.base_url
        )
        with self.assertRaises(EmbeddingProviderError):
            provider.embed_texts(["one", "two"])

    def test_http_error_is_wrapped(self):
        _EmbeddingFixtureHandler.behavior = "http-error"
        provider = OllamaEmbeddingProvider(
            "nomic-embed-text", base_url=self.base_url
        )
        with self.assertRaises(EmbeddingProviderError):
            provider.embed_texts(["one"])

    def test_malformed_json_is_rejected(self):
        _EmbeddingFixtureHandler.behavior = "bad-json"
        provider = OllamaEmbeddingProvider(
            "nomic-embed-text", base_url=self.base_url
        )
        with self.assertRaises(EmbeddingProviderError):
            provider.embed_texts(["one"])

    def test_unreachable_endpoint_is_wrapped(self):
        provider = OllamaEmbeddingProvider(
            "nomic-embed-text", base_url="http://127.0.0.1:1"
        )
        with self.assertRaises(EmbeddingProviderError):
            provider.embed_texts(["one"])

    def test_configuration_validation(self):
        with self.assertRaises(EmbeddingProviderError):
            OllamaEmbeddingProvider("")
        with self.assertRaises(EmbeddingProviderError):
            OllamaEmbeddingProvider("has space")
        with self.assertRaises(EmbeddingProviderError):
            OllamaEmbeddingProvider("model", base_url="ftp://127.0.0.1")
        with self.assertRaises(EmbeddingProviderError):
            OllamaEmbeddingProvider("model", timeout=0)
        with patch.dict("os.environ", {"OLLAMA_BASE_URL": self.base_url}):
            provider = OllamaEmbeddingProvider("nomic-embed-text")
            self.assertEqual(provider.base_url, self.base_url)


if __name__ == "__main__":
    unittest.main()
