"""SQLite metadata index over the file-authoritative MemoryStore (Phase F).

The Markdown store under ``.auto-memory`` stays the single source of truth.
This adapter derives a rebuildable, single-file metadata index that can be
reconciled from any machine, so memory metadata becomes migratable without
copying the entry files. Every row cites the authoritative ``entry_id`` and
carries a SHA-256 ``content_hash`` of the indexed body.

Design invariants:
- stdlib ``sqlite3`` only; no new execution authority.
- Bounded and fail-closed: an over-budget entry aborts the whole reconcile
  and leaves the previous index content untouched.
- Deterministic: the same entry set produces the same index rows and the
  same fingerprint, so repeat reconciles skip the rewrite entirely.
- Read-only mode never writes and never creates the database file.

Run: python sqlite_memory_index.py <db_path> stats
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import struct
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence, Tuple

from core.contracts.embedding_provider import (
    EMBEDDING_MAX_DIMS,
    validate_embedding_model_id,
)

INDEX_SCHEMA_VERSION = 3
INDEX_MAX_ENTRIES = 8_192
INDEX_MAX_ID_CHARS = 128
INDEX_MAX_TITLE_CHARS = 4_096
INDEX_MAX_CONTENT_CHARS = 1_048_576
INDEX_MAX_TAGS = 64
INDEX_MAX_TAG_CHARS = 256
INDEX_MAX_TIMESTAMP_CHARS = 128
INDEX_MAX_METADATA_JSON_CHARS = 16_384
# Mirrors core.contracts.memory_search.FULLTEXT_MIN_TERM_CHARS: the trigram
# tokenizer cannot match shorter substrings, so shorter terms stay lexical.
INDEX_FTS_MIN_TERM_CHARS = 3
INDEX_MAX_FTS_TERMS = 8

_SCHEMA_SQL = (
    """
    CREATE TABLE IF NOT EXISTS index_meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS memory_entries (
        entry_id TEXT PRIMARY KEY,
        memory_type TEXT NOT NULL,
        title TEXT NOT NULL,
        content TEXT NOT NULL,
        tags_json TEXT NOT NULL,
        metadata_json TEXT NOT NULL,
        parent_id TEXT,
        created_at TEXT NOT NULL,
        last_accessed TEXT NOT NULL,
        access_count INTEGER NOT NULL,
        importance REAL NOT NULL,
        token_count INTEGER NOT NULL,
        content_hash TEXT NOT NULL
    )
    """,
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
        title,
        content,
        tags,
        entry_id UNINDEXED,
        tokenize = 'trigram'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS memory_vectors (
        entry_id TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        model_id TEXT NOT NULL,
        dims INTEGER NOT NULL,
        vector BLOB NOT NULL,
        PRIMARY KEY (entry_id, model_id)
    )
    """,
)

_ENTRY_COLUMNS = (
    "entry_id",
    "memory_type",
    "title",
    "content",
    "tags_json",
    "metadata_json",
    "parent_id",
    "created_at",
    "last_accessed",
    "access_count",
    "importance",
    "token_count",
    "content_hash",
)


class SqliteMemoryIndexError(RuntimeError):
    """Raised when the index cannot be opened, reconciled or read safely."""


@dataclass(frozen=True)
class SqliteMemoryRow:
    """One indexed memory entry with its provenance fields."""

    id: str
    memory_type: str
    title: str
    content: str
    tags: tuple[str, ...]
    metadata: Dict[str, Any]
    parent_id: str | None
    created_at: str
    last_accessed: str
    access_count: int
    importance: float
    token_count: int
    content_hash: str


def _bounded_str(value: Any, field: str, limit: int, *, required: bool = True) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str):
        raise SqliteMemoryIndexError(f"{field} must be a string")
    if len(value) > limit:
        raise SqliteMemoryIndexError(
            f"{field} exceeds the {limit} character index budget"
        )
    return value


def _memory_type_value(entry: Any) -> str:
    memory_type = getattr(entry, "type", None)
    value = getattr(memory_type, "value", memory_type)
    if not isinstance(value, str) or not value:
        raise SqliteMemoryIndexError("entry type must resolve to a non-empty string")
    return value


def _bounded_tags(entry: Any) -> tuple[str, ...]:
    tags = getattr(entry, "tags", None)
    if tags is None:
        return ()
    if not isinstance(tags, (list, tuple)):
        raise SqliteMemoryIndexError("entry tags must be a list")
    if len(tags) > INDEX_MAX_TAGS:
        raise SqliteMemoryIndexError(
            f"entry tags exceed the {INDEX_MAX_TAGS} item index budget"
        )
    bounded: list[str] = []
    for tag in tags:
        if not isinstance(tag, str):
            raise SqliteMemoryIndexError("entry tags must contain strings only")
        bounded.append(_bounded_str(tag, "entry tag", INDEX_MAX_TAG_CHARS))
    return tuple(bounded)


def _bounded_metadata(entry: Any) -> Dict[str, Any]:
    metadata = getattr(entry, "metadata", None)
    if metadata is None:
        return {}
    if not isinstance(metadata, dict):
        raise SqliteMemoryIndexError("entry metadata must be an object")
    try:
        serialized = json.dumps(
            metadata,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as error:
        raise SqliteMemoryIndexError(
            "entry metadata must be JSON serializable"
        ) from error
    if len(serialized) > INDEX_MAX_METADATA_JSON_CHARS:
        raise SqliteMemoryIndexError(
            "entry metadata exceeds the "
            f"{INDEX_MAX_METADATA_JSON_CHARS} character index budget"
        )
    return metadata


def _bounded_content(entry: Any) -> str:
    content = getattr(entry, "content", None)
    if not isinstance(content, str):
        raise SqliteMemoryIndexError("entry content must be a string")
    if len(content) > INDEX_MAX_CONTENT_CHARS:
        raise SqliteMemoryIndexError(
            "entry content exceeds the "
            f"{INDEX_MAX_CONTENT_CHARS} character index budget"
        )
    return content


def _bounded_entry_id(entry: Any) -> str:
    entry_id = getattr(entry, "id", None)
    if not isinstance(entry_id, str) or not entry_id:
        raise SqliteMemoryIndexError("entry id must be a non-empty string")
    if len(entry_id) > INDEX_MAX_ID_CHARS:
        raise SqliteMemoryIndexError(
            f"entry id exceeds the {INDEX_MAX_ID_CHARS} character index budget"
        )
    return entry_id


def _index_row(entry: Any) -> SqliteMemoryRow:
    entry_id = _bounded_entry_id(entry)
    content = _bounded_content(entry)
    title = _bounded_str(
        getattr(entry, "title", None), "entry title", INDEX_MAX_TITLE_CHARS
    )
    tags = _bounded_tags(entry)
    metadata = _bounded_metadata(entry)
    parent_id = getattr(entry, "parent_id", None)
    if parent_id is not None:
        parent_id = _bounded_str(parent_id, "entry parent_id", INDEX_MAX_ID_CHARS)

    access_count = getattr(entry, "access_count", 0)
    token_count = getattr(entry, "token_count", 0)
    importance = getattr(entry, "importance", 0.0)
    if isinstance(access_count, bool) or not isinstance(access_count, int):
        raise SqliteMemoryIndexError("entry access_count must be an integer")
    if isinstance(token_count, bool) or not isinstance(token_count, int):
        raise SqliteMemoryIndexError("entry token_count must be an integer")
    if isinstance(importance, bool) or not isinstance(importance, (int, float)):
        raise SqliteMemoryIndexError("entry importance must be a number")

    return SqliteMemoryRow(
        id=entry_id,
        memory_type=_memory_type_value(entry),
        title=title,
        content=content,
        tags=tags,
        metadata=metadata,
        parent_id=parent_id,
        created_at=_bounded_str(
            getattr(entry, "created_at", ""),
            "entry created_at",
            INDEX_MAX_TIMESTAMP_CHARS,
        ),
        last_accessed=_bounded_str(
            getattr(entry, "last_accessed", ""),
            "entry last_accessed",
            INDEX_MAX_TIMESTAMP_CHARS,
        ),
        access_count=max(0, access_count),
        importance=float(importance),
        token_count=max(0, token_count),
        content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
    )


def _validated_unit_vector(vector: Any, label: str) -> List[float]:
    """Validate a bounded numeric vector and normalize it to unit length."""
    if not isinstance(vector, (list, tuple)) or not vector:
        raise SqliteMemoryIndexError(f"{label} must be a non-empty numeric list")
    if len(vector) > EMBEDDING_MAX_DIMS:
        raise SqliteMemoryIndexError(
            f"{label} exceeds {EMBEDDING_MAX_DIMS} dimensions"
        )
    values: List[float] = []
    for value in vector:
        if type(value) is not float and type(value) is not int:
            raise SqliteMemoryIndexError(f"{label} values must be numbers")
        if not math.isfinite(value):
            raise SqliteMemoryIndexError(f"{label} values must be finite")
        values.append(float(value))
    norm = math.sqrt(sum(value * value for value in values))
    if norm <= 0.0:
        raise SqliteMemoryIndexError(f"{label} must have a positive norm")
    return [value / norm for value in values]


def _fulltext_match_terms(terms: Sequence[str]) -> List[str]:
    """Bound and quote-safety-check trigram terms before building MATCH."""
    cleaned: List[str] = []
    for term in terms:
        if not isinstance(term, str):
            raise SqliteMemoryIndexError("full-text terms must be strings")
        if len(term) < INDEX_FTS_MIN_TERM_CHARS:
            raise SqliteMemoryIndexError(
                "full-text terms need at least "
                f"{INDEX_FTS_MIN_TERM_CHARS} characters"
            )
        if len(term) > INDEX_MAX_ID_CHARS or '"' in term:
            raise SqliteMemoryIndexError(
                "full-text term exceeds the safe match budget"
            )
        if term not in cleaned:
            cleaned.append(term)
        if len(cleaned) >= INDEX_MAX_FTS_TERMS:
            break
    return cleaned


def _row_fingerprint(rows: Sequence[SqliteMemoryRow]) -> str:
    payload = json.dumps(
        [
            [
                row.id,
                row.memory_type,
                row.title,
                row.content,
                list(row.tags),
                row.metadata,
                row.parent_id,
                row.created_at,
                row.last_accessed,
                row.access_count,
                row.importance,
                row.token_count,
            ]
            for row in sorted(rows, key=lambda item: item.id)
        ],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class SqliteMemoryIndex:
    """Bounded SQLite metadata index reconciled from MemoryStore entries."""

    def __init__(self, db_path: str | Path, *, read_only: bool = False) -> None:
        self._db_path = Path(db_path)
        self._read_only = bool(read_only)
        # Reentrant: reconcile holds the lock across its transaction while
        # re-entering the bounded meta readers.
        self._lock = threading.RLock()
        self._conn = self._connect()
        try:
            self._ensure_schema()
        except Exception:
            self._conn.close()
            raise

    @property
    def db_path(self) -> Path:
        return self._db_path

    @property
    def read_only(self) -> bool:
        return self._read_only

    def _connect(self) -> sqlite3.Connection:
        try:
            if self._read_only:
                if not self._db_path.is_file():
                    raise SqliteMemoryIndexError(
                        f"memory index database does not exist: {self._db_path}"
                    )
                uri = f"{self._db_path.resolve().as_uri()}?mode=ro"
                return sqlite3.connect(
                    uri,
                    uri=True,
                    timeout=5.0,
                    check_same_thread=False,
                )
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            return sqlite3.connect(
                str(self._db_path),
                timeout=5.0,
                check_same_thread=False,
            )
        except SqliteMemoryIndexError:
            raise
        except sqlite3.Error as error:
            raise SqliteMemoryIndexError(
                f"cannot open memory index {self._db_path}: {error}"
            ) from error

    def _ensure_schema(self) -> None:
        if not self._fts5_supported():
            raise SqliteMemoryIndexError(
                "this SQLite build has no FTS5 trigram support; "
                f"memory index schema version {INDEX_SCHEMA_VERSION} requires it"
            )
        try:
            with self._lock:
                for statement in _SCHEMA_SQL:
                    self._conn.execute(statement)
                self._conn.commit()
                row = self._conn.execute(
                    "SELECT value FROM index_meta WHERE key = 'schema_version'"
                ).fetchone()
        except sqlite3.Error as error:
            raise SqliteMemoryIndexError(
                f"cannot initialize memory index schema: {error}"
            ) from error
        if row is None:
            if self._read_only:
                raise SqliteMemoryIndexError(
                    "read-only memory index is missing its schema version"
                )
            self._write_meta("schema_version", str(INDEX_SCHEMA_VERSION))
            return
        try:
            stored_version = int(row[0])
        except (TypeError, ValueError) as error:
            raise SqliteMemoryIndexError(
                "memory index schema version is malformed"
            ) from error
        if stored_version == INDEX_SCHEMA_VERSION:
            return
        if self._read_only:
            raise SqliteMemoryIndexError(
                f"read-only memory index has schema version {stored_version}; "
                "rebuild the index against schema version "
                f"{INDEX_SCHEMA_VERSION} to read it"
            )
        if stored_version < INDEX_SCHEMA_VERSION:
            # Versions 1 and 2 predate later derived tables. The index is
            # derived data the authoritative Markdown store can always
            # rebuild, so the upgrade is a transparent full reset; the next
            # reconcile repopulates it.
            self._reset_schema(f"from version {stored_version}")
            return
        raise SqliteMemoryIndexError(
            f"memory index schema version {stored_version} is not supported "
            f"(expected {INDEX_SCHEMA_VERSION}); rebuild the index explicitly"
        )

    @staticmethod
    def _fts5_supported() -> bool:
        try:
            probe = sqlite3.connect(":memory:")
            try:
                probe.execute(
                    "CREATE VIRTUAL TABLE temp.memory_fts_probe "
                    "USING fts5(x, tokenize='trigram')"
                )
            finally:
                probe.close()
        except sqlite3.Error:
            return False
        return True

    def _reset_schema(self, reason: str) -> None:
        try:
            with self._lock:
                with self._conn:
                    self._conn.execute("DROP TABLE IF EXISTS memory_fts")
                    self._conn.execute("DROP TABLE IF EXISTS memory_vectors")
                    self._conn.execute("DROP TABLE IF EXISTS memory_entries")
                    self._conn.execute("DELETE FROM index_meta")
                    for statement in _SCHEMA_SQL:
                        self._conn.execute(statement)
        except sqlite3.Error as error:
            raise SqliteMemoryIndexError(
                f"cannot reset memory index schema {reason}: {error}"
            ) from error
        self._write_meta("schema_version", str(INDEX_SCHEMA_VERSION))

    def _write_meta(self, key: str, value: str) -> None:
        try:
            with self._lock:
                with self._conn:
                    self._conn.execute(
                        "INSERT OR REPLACE INTO index_meta (key, value) "
                        "VALUES (?, ?)",
                        (key, value),
                    )
        except sqlite3.Error as error:
            raise SqliteMemoryIndexError(
                f"cannot write memory index metadata: {error}"
            ) from error

    def _read_meta(self, key: str) -> str | None:
        try:
            with self._lock:
                row = self._conn.execute(
                    "SELECT value FROM index_meta WHERE key = ?", (key,)
                ).fetchone()
        except sqlite3.Error as error:
            raise SqliteMemoryIndexError(
                f"cannot read memory index metadata: {error}"
            ) from error
        return None if row is None else str(row[0])

    def reconcile(self, entries: Sequence[Any]) -> Dict[str, int]:
        """Replace index content with the bounded authoritative snapshot.

        Rows are rebuilt in one transaction; a matching fingerprint skips
        the rewrite so unchanged stores do not churn the database file.
        """
        rows = [_index_row(entry) for entry in entries]
        if len(rows) > INDEX_MAX_ENTRIES:
            raise SqliteMemoryIndexError(
                f"entry set exceeds the {INDEX_MAX_ENTRIES} row index budget"
            )
        if len({row.id for row in rows}) != len(rows):
            raise SqliteMemoryIndexError("entry set contains duplicate ids")
        fingerprint = _row_fingerprint(rows)
        if self._read_only:
            raise SqliteMemoryIndexError(
                "read-only memory index cannot reconcile entries"
            )
        try:
            with self._lock:
                stored = self._read_meta("entry_fingerprint")
                if stored == fingerprint:
                    return {"entries": len(rows), "reconciled": 0}
                with self._conn:
                    self._conn.execute("DELETE FROM memory_entries")
                    self._conn.executemany(
                        "INSERT INTO memory_entries "
                        "(entry_id, memory_type, title, content, tags_json, "
                        "metadata_json, parent_id, created_at, last_accessed, "
                        "access_count, importance, token_count, content_hash) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        [
                            (
                                row.id,
                                row.memory_type,
                                row.title,
                                row.content,
                                json.dumps(
                                    list(row.tags),
                                    ensure_ascii=False,
                                    separators=(",", ":"),
                                ),
                                json.dumps(
                                    row.metadata,
                                    ensure_ascii=False,
                                    sort_keys=True,
                                    separators=(",", ":"),
                                ),
                                row.parent_id,
                                row.created_at,
                                row.last_accessed,
                                row.access_count,
                                row.importance,
                                row.token_count,
                                row.content_hash,
                            )
                            for row in sorted(rows, key=lambda item: item.id)
                        ],
                    )
                    self._conn.execute("DELETE FROM memory_fts")
                    self._conn.executemany(
                        "INSERT INTO memory_fts (entry_id, title, content, tags) "
                        "VALUES (?, ?, ?, ?)",
                        [
                            (
                                row.id,
                                row.title,
                                row.content,
                                " ".join(row.tags),
                            )
                            for row in sorted(rows, key=lambda item: item.id)
                        ],
                    )
                    self._conn.execute(
                        "DELETE FROM memory_vectors "
                        "WHERE entry_id NOT IN (SELECT entry_id FROM memory_entries)"
                    )
                    self._conn.execute(
                        "INSERT OR REPLACE INTO index_meta (key, value) "
                        "VALUES ('entry_fingerprint', ?)",
                        (fingerprint,),
                    )
        except sqlite3.Error as error:
            raise SqliteMemoryIndexError(
                f"cannot reconcile memory index: {error}"
            ) from error
        return {"entries": len(rows), "reconciled": 1}

    def fetch_entries(
        self, max_rows: int = INDEX_MAX_ENTRIES
    ) -> List[SqliteMemoryRow]:
        """Return index rows ordered by entry id, bounded by ``max_rows``."""
        if isinstance(max_rows, bool) or not isinstance(max_rows, int) or max_rows < 0:
            raise SqliteMemoryIndexError("max_rows must be a non-negative integer")
        try:
            with self._lock:
                cursor = self._conn.execute(
                    f"SELECT {', '.join(_ENTRY_COLUMNS)} FROM memory_entries "
                    "ORDER BY entry_id LIMIT ?",
                    (max_rows,),
                )
                raw_rows = cursor.fetchall()
        except sqlite3.Error as error:
            raise SqliteMemoryIndexError(
                f"cannot read memory index entries: {error}"
            ) from error
        parsed: List[SqliteMemoryRow] = []
        for raw in raw_rows:
            parsed.append(self._row_from_db(raw))
        return parsed

    def _row_from_db(self, raw: Sequence[Any]) -> SqliteMemoryRow:
        record = dict(zip(_ENTRY_COLUMNS, raw))
        try:
            tags = json.loads(record["tags_json"])
            metadata = json.loads(record["metadata_json"])
        except (TypeError, ValueError) as error:
            raise SqliteMemoryIndexError(
                "memory index row contains malformed JSON metadata"
            ) from error
        if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
            raise SqliteMemoryIndexError(
                "memory index row contains malformed tags"
            )
        if not isinstance(metadata, dict):
            raise SqliteMemoryIndexError(
                "memory index row contains malformed metadata"
            )
        return SqliteMemoryRow(
            id=str(record["entry_id"]),
            memory_type=str(record["memory_type"]),
            title=str(record["title"]),
            content=str(record["content"]),
            tags=tuple(tags),
            metadata=metadata,
            parent_id=None if record["parent_id"] is None else str(record["parent_id"]),
            created_at=str(record["created_at"]),
            last_accessed=str(record["last_accessed"]),
            access_count=int(record["access_count"]),
            importance=float(record["importance"]),
            token_count=int(record["token_count"]),
            content_hash=str(record["content_hash"]),
        )

    def search_fulltext(
        self, terms: Sequence[str], *, max_rows: int = INDEX_MAX_ENTRIES
    ) -> List[Tuple[SqliteMemoryRow, float]]:
        """Run a bounded trigram full-text query ordered by BM25 relevance.

        Terms are OR-combined so a row matching any term is a candidate;
        ``rank`` (BM25) orders best matches first. Each hit pairs the entry
        row with its positive relevance (``-rank``).
        """
        if (
            isinstance(max_rows, bool)
            or not isinstance(max_rows, int)
            or not 0 <= max_rows <= INDEX_MAX_ENTRIES
        ):
            raise SqliteMemoryIndexError(
                f"max_rows must be between 0 and {INDEX_MAX_ENTRIES}"
            )
        cleaned = _fulltext_match_terms(terms)
        if not cleaned:
            return []
        match_expression = " OR ".join(f'"{term}"' for term in cleaned)
        try:
            with self._lock:
                cursor = self._conn.execute(
                    f"SELECT {', '.join('e.' + column for column in _ENTRY_COLUMNS)}, "
                    "memory_fts.rank FROM memory_fts "
                    "JOIN memory_entries AS e ON e.entry_id = memory_fts.entry_id "
                    "WHERE memory_fts MATCH ? "
                    "ORDER BY memory_fts.rank LIMIT ?",
                    (match_expression, max_rows),
                )
                raw_rows = cursor.fetchall()
        except sqlite3.Error as error:
            raise SqliteMemoryIndexError(
                f"cannot run memory full-text query: {error}"
            ) from error
        hits: List[Tuple[SqliteMemoryRow, float]] = []
        for raw in raw_rows:
            relevance = float(-raw[len(_ENTRY_COLUMNS)])
            hits.append((self._row_from_db(raw), relevance))
        return hits

    def vector_backlog(
        self,
        rows: Sequence[SqliteMemoryRow],
        model_id: str,
    ) -> List[SqliteMemoryRow]:
        """Rows lacking a current-model vector for their content hash."""
        model = validate_embedding_model_id(model_id)
        try:
            with self._lock:
                cursor = self._conn.execute(
                    "SELECT entry_id, content_hash FROM memory_vectors "
                    "WHERE model_id = ?",
                    (model,),
                )
                stored = {row[0]: row[1] for row in cursor.fetchall()}
        except sqlite3.Error as error:
            raise SqliteMemoryIndexError(
                f"cannot read memory vector coverage: {error}"
            ) from error
        return [
            row
            for row in rows
            if stored.get(row.id) != row.content_hash
        ][:INDEX_MAX_ENTRIES]

    def store_vectors(
        self,
        model_id: str,
        vectors: Mapping[str, Tuple[str, Sequence[float]]],
    ) -> int:
        """Persist normalized float32 vectors keyed by entry and model."""
        model = validate_embedding_model_id(model_id)
        if not isinstance(vectors, dict):
            raise SqliteMemoryIndexError("vectors must be a mapping by entry id")
        if len(vectors) > INDEX_MAX_ENTRIES:
            raise SqliteMemoryIndexError(
                f"vector batch exceeds the {INDEX_MAX_ENTRIES} row index budget"
            )
        packed: List[Tuple[str, str, str, int, bytes]] = []
        dims_seen: int | None = None
        for entry_id, pair in vectors.items():
            if (
                not isinstance(entry_id, str)
                or not entry_id
                or len(entry_id) > INDEX_MAX_ID_CHARS
            ):
                raise SqliteMemoryIndexError("vector entry id must be a bounded string")
            if not isinstance(pair, tuple) or len(pair) != 2:
                raise SqliteMemoryIndexError(
                    "vector values must be (content_hash, vector) pairs"
                )
            content_hash, vector = pair
            if not isinstance(content_hash, str) or not content_hash:
                raise SqliteMemoryIndexError(
                    "vector content hash must be a non-empty string"
                )
            unit = _validated_unit_vector(vector, "stored vector")
            dims = len(unit)
            if dims_seen is None:
                dims_seen = dims
            elif dims != dims_seen:
                raise SqliteMemoryIndexError(
                    "stored vectors must share one dimensionality"
                )
            packed.append(
                (entry_id, content_hash, model, dims, struct.pack(f"<{dims}f", *unit))
            )
        try:
            with self._lock:
                with self._conn:
                    self._conn.executemany(
                        "INSERT OR REPLACE INTO memory_vectors "
                        "(entry_id, content_hash, model_id, dims, vector) "
                        "VALUES (?, ?, ?, ?, ?)",
                        packed,
                    )
        except sqlite3.Error as error:
            raise SqliteMemoryIndexError(
                f"cannot store memory vectors: {error}"
            ) from error
        return len(packed)

    def search_semantic(
        self,
        query_vector: Sequence[float],
        model_id: str,
        *,
        max_rows: int = INDEX_MAX_ENTRIES,
    ) -> List[Tuple[SqliteMemoryRow, float]]:
        """Rank indexed entries by cosine similarity to the query vector.

        Only vectors whose content hash still matches the authoritative
        entry participate; rows stored with a different dimensionality are
        skipped defensively. Ties break by entry id for determinism.
        """
        model = validate_embedding_model_id(model_id)
        if (
            isinstance(max_rows, bool)
            or not isinstance(max_rows, int)
            or not 0 <= max_rows <= INDEX_MAX_ENTRIES
        ):
            raise SqliteMemoryIndexError(
                f"max_rows must be between 0 and {INDEX_MAX_ENTRIES}"
            )
        query = _validated_unit_vector(query_vector, "query vector")
        try:
            with self._lock:
                cursor = self._conn.execute(
                    f"SELECT {', '.join('e.' + column for column in _ENTRY_COLUMNS)}, "
                    "v.vector FROM memory_vectors AS v "
                    "JOIN memory_entries AS e ON e.entry_id = v.entry_id "
                    "AND e.content_hash = v.content_hash "
                    "WHERE v.model_id = ?",
                    (model,),
                )
                raw_rows = cursor.fetchall()
        except sqlite3.Error as error:
            raise SqliteMemoryIndexError(
                f"cannot run memory semantic query: {error}"
            ) from error
        scored: List[Tuple[float, Sequence[Any]]] = []
        for raw in raw_rows:
            blob = raw[len(_ENTRY_COLUMNS)]
            if not isinstance(blob, bytes) or len(blob) % 4 != 0:
                continue
            dims = len(blob) // 4
            if dims != len(query):
                continue
            vector = struct.unpack(f"<{dims}f", blob)
            similarity = sum(left * right for left, right in zip(query, vector))
            scored.append((similarity, raw))
        scored.sort(key=lambda item: (-item[0], item[1][0]))
        return [
            (self._row_from_db(raw), float(similarity))
            for similarity, raw in scored[:max_rows]
        ]

    def stats(self) -> Dict[str, Any]:
        """Return bounded index health: schema version, rows, fingerprint."""
        try:
            with self._lock:
                count_row = self._conn.execute(
                    "SELECT COUNT(*) FROM memory_entries"
                ).fetchone()
                vector_row = self._conn.execute(
                    "SELECT COUNT(*) FROM memory_vectors"
                ).fetchone()
        except sqlite3.Error as error:
            raise SqliteMemoryIndexError(
                f"cannot read memory index stats: {error}"
            ) from error
        return {
            "schema_version": INDEX_SCHEMA_VERSION,
            "entries": int(count_row[0]) if count_row is not None else 0,
            "vectors": int(vector_row[0]) if vector_row is not None else 0,
            "fingerprint": self._read_meta("entry_fingerprint"),
            "read_only": self._read_only,
            "fts5": True,
        }

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python sqlite_memory_index.py <db_path> [stats]")
        sys.exit(0)
    db_path = Path(sys.argv[1])
    if not db_path.is_file():
        print(f"memory index database does not exist: {db_path}")
        sys.exit(1)
    index = SqliteMemoryIndex(db_path, read_only=True)
    try:
        print(json.dumps(index.stats(), ensure_ascii=False, indent=2))
    finally:
        index.close()


if __name__ == "__main__":
    main()
