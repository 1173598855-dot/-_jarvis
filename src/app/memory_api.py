"""Shared bounded helpers for the standard-library and FastAPI memory APIs."""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from weakref import WeakKeyDictionary

from adapters.sqlite_memory_index import (
    INDEX_MAX_ENTRIES,
    SqliteMemoryIndex,
)
from core.brain.context_compressor import MemoryEntry, MemoryStore, MemoryType
from core.contracts.embedding_provider import (
    EMBEDDING_MAX_TEXT_CHARS,
    EmbeddingProviderError,
)
from core.contracts.memory_repository import MemoryRepository
from core.contracts.memory_search import (
    MAX_MEMORY_QUERY_CHARS,
    memory_fulltext_terms,
    memory_matches,
    memory_query_terms,
    memory_score,
    memory_snippet_text,
    memory_source_ids,
)
from core.kernel.secret_redaction import redact_value

MEMORY_API_MAX_DIRECTORY_ENTRIES = 8_192
MEMORY_API_MAX_FILES = 256
MEMORY_API_MAX_FILE_BYTES = 1024 * 1024
MEMORY_API_MAX_TOTAL_BYTES = 32 * 1024 * 1024
MEMORY_API_MAX_TITLE_CHARS = 512
MEMORY_API_MAX_TIMESTAMP_CHARS = 128
MEMORY_API_MAX_TAGS = 64
MEMORY_API_MAX_TAG_CHARS = 256
MEMORY_API_DEFAULT_SEARCH_RESULTS = 10
MEMORY_API_MAX_SEARCH_RESULTS = 50
MEMORY_API_SEARCH_MODES = ("lexical", "fulltext", "semantic")
MEMORY_API_SEMANTIC_MAX_EMBEDS = 32
MEMORY_API_MAX_IMPORT_ENTRIES = 256
MEMORY_API_MAX_IMPORT_ERRORS = 32
MEMORY_API_MAX_PRUNE_PER_REQUEST = 64
MEMORY_API_PRUNE_MAX_ENTRIES = 8_192
MEMORY_API_PRUNE_MAX_AGE_DAYS = 3_650
MEMORY_PRUNE_EXCLUDED_METADATA_KEY = "probe_cleanup_token"
MEMORY_PRUNE_ALLOWED_KEYS = frozenset(
    {"max_entries", "max_age_days", "min_importance", "dry_run"}
)
MEMORY_BACKUP_MAX_RETAINED = 8
MEMORY_BACKUP_MAX_BYTES = 33 * 1024 * 1024
# The 21-character stamp (8 digits, T separator, 12 digits) carries
# microsecond precision, so name order is creation order; filesystem mtime
# is too coarse for back-to-back writes on Windows.
MEMORY_BACKUP_NAME_RE = re.compile(
    r"^backup-[0-9]{8}T[0-9]{12}-[0-9a-f]{8}\.json$"
)

BACKUPS_DIRNAME = "backups"
BACKUP_SCHEMA_VERSION = 1

INDEX_DB_FILENAME = "memory-index.sqlite3"

_INDEX_CACHE: "WeakKeyDictionary[Any, SqliteMemoryIndex]" = WeakKeyDictionary()
_INDEX_CACHE_LOCK = threading.Lock()


class MemorySearchRequestError(ValueError):
    """Raised when a memory search request violates the bounded contract."""


class MemorySemanticUnavailableError(RuntimeError):
    """Raised when semantic mode cannot run against its embedding provider."""


class MemoryTransferRequestError(ValueError):
    """Raised when a memory export/import request violates the contract."""


class MemoryBackupNotFoundError(MemoryTransferRequestError):
    """Raised when a named memory backup does not exist."""


class MemoryBackupFailedError(RuntimeError):
    """Raised when a memory backup cannot be written or verified."""


def load_memory_entries_for_api(
    memory_store: MemoryRepository,
    memory_type: Any,
    *,
    max_directory_entries: int = MEMORY_API_MAX_DIRECTORY_ENTRIES,
    max_files: int = MEMORY_API_MAX_FILES,
    max_file_bytes: int = MEMORY_API_MAX_FILE_BYTES,
    max_total_bytes: int = MEMORY_API_MAX_TOTAL_BYTES,
) -> list[Any]:
    """Read a bounded, descriptor-checked snapshot for public listing."""
    if getattr(memory_store, "read_only", False):
        reader = memory_store
    else:
        reader = MemoryStore(
            memory_dir=str(memory_store.memory_dir),
            read_only=True,
        )
    return reader.load(
        memory_type,
        max_directory_entries=max_directory_entries,
        max_files=max_files,
        max_file_bytes=max_file_bytes,
        max_total_bytes=max_total_bytes,
    )


def public_memory_entry(entry: Any) -> dict[str, Any]:
    """Project one memory entry into the bounded public API shape."""
    return {
        "id": entry.id,
        "type": entry.type.value,
        "title": entry.title[:MEMORY_API_MAX_TITLE_CHARS],
        "content": entry.content[:200],
        "created_at": entry.created_at[:MEMORY_API_MAX_TIMESTAMP_CHARS],
        "tags": [
            tag[:MEMORY_API_MAX_TAG_CHARS]
            for tag in entry.tags[:MEMORY_API_MAX_TAGS]
        ],
        "access_count": entry.access_count,
    }


def _memory_index_for_store(memory_store: Any) -> SqliteMemoryIndex:
    """Open (once per store instance) the migratable SQLite metadata index."""
    with _INDEX_CACHE_LOCK:
        index = _INDEX_CACHE.get(memory_store)
        if index is None:
            memory_dir = Path(str(memory_store.memory_dir))
            index = SqliteMemoryIndex(memory_dir / INDEX_DB_FILENAME)
            _INDEX_CACHE[memory_store] = index
        return index


def close_memory_search_indexes() -> None:
    """Close and drop every cached index connection (shutdown and test support)."""
    with _INDEX_CACHE_LOCK:
        for index in list(_INDEX_CACHE.values()):
            try:
                index.close()
            except Exception:
                pass
        _INDEX_CACHE.clear()


def search_memory_entries_for_api(
    memory_store: Any,
    query: Any,
    *,
    limit: Any = MEMORY_API_DEFAULT_SEARCH_RESULTS,
    mode: Any = "lexical",
    embedding_provider: Any = None,
) -> dict[str, Any]:
    """Reconcile the SQLite index and run the shared search contract.

    ``lexical`` keeps the deterministic 5x/3x/1x scoring; ``fulltext`` uses
    FTS5 trigram matching with BM25 relevance; ``semantic`` embeds the query
    through the configured provider and ranks by cosine similarity, catching
    up a bounded embedding backlog per request. All modes reconcile against
    the bounded Markdown snapshot, which stays authoritative, and skip the
    rewrite entirely when the entry fingerprint is unchanged.
    """
    if type(query) is not str:
        raise MemorySearchRequestError("Memory search query must be a string")
    if type(limit) is not int:
        raise MemorySearchRequestError("Memory search limit must be an integer")
    if limit < 1:
        raise MemorySearchRequestError("Memory search limit must be at least 1")
    if mode not in MEMORY_API_SEARCH_MODES:
        raise MemorySearchRequestError(
            "Memory search mode must be 'lexical', 'fulltext' or 'semantic'"
        )
    limit = min(limit, MEMORY_API_MAX_SEARCH_RESULTS)

    entries = load_memory_entries_for_api(memory_store, None)
    index = _memory_index_for_store(memory_store)
    index.reconcile(entries)
    rows = index.fetch_entries(max_rows=INDEX_MAX_ENTRIES)

    coverage: dict[str, int] | None = None
    if mode == "fulltext":
        try:
            terms = memory_fulltext_terms(query)
        except ValueError as error:
            raise MemorySearchRequestError(str(error)) from error
        hits = index.search_fulltext(terms, max_rows=INDEX_MAX_ENTRIES)
        matches: list[dict[str, Any]] = []
        for row, relevance in hits:
            matches.append({
                "id": row.id[:128],
                "type": row.memory_type,
                "title": row.title[:256],
                "snippet": memory_snippet_text(
                    str(redact_value(row.content)), terms
                ),
                "score": relevance,
                "parent_id": row.parent_id if row.parent_id is None else str(row.parent_id)[:128],
                "source_ids": memory_source_ids(row),
            })
            if len(matches) >= limit:
                break
    elif mode == "semantic":
        matches, coverage = _semantic_matches(
            index, rows, query, limit=limit, embedding_provider=embedding_provider
        )
    else:
        try:
            terms = memory_query_terms(query)
        except ValueError as error:
            raise MemorySearchRequestError(str(error)) from error
        matches = []
        for row in rows:
            if not memory_matches(row, terms):
                continue
            matches.append({
                "id": row.id[:128],
                "type": row.memory_type,
                "title": row.title[:256],
                "snippet": memory_snippet_text(str(redact_value(row.content)), terms),
                "score": memory_score(row, terms),
                "parent_id": row.parent_id if row.parent_id is None else str(row.parent_id)[:128],
                "source_ids": memory_source_ids(row),
            })
            if len(matches) >= limit:
                break
    ranked = sorted(matches, key=lambda item: (-item["score"], item["title"], item["id"]))
    response: dict[str, Any] = {
        "mode": mode,
        "query": query,
        "count": len(ranked),
        "results": ranked,
    }
    if coverage is not None:
        response["coverage"] = coverage
    return response


def _semantic_matches(
    index: SqliteMemoryIndex,
    rows: list[Any],
    query: str,
    *,
    limit: int,
    embedding_provider: Any,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Embed the bounded backlog, then rank entries by cosine similarity."""
    if embedding_provider is None:
        raise MemorySemanticUnavailableError(
            "semantic mode requires a configured embedding provider "
            "(JARVIS_MEMORY_EMBED_MODEL)"
        )
    if not query.strip() or len(query.strip()) > MAX_MEMORY_QUERY_CHARS:
        raise MemorySearchRequestError("Memory query must contain 1 to 256 characters")
    model = embedding_provider.model_id

    backlog = index.vector_backlog(rows, model)
    if backlog:
        batch = backlog[:MEMORY_API_SEMANTIC_MAX_EMBEDS]
        texts = [row.content[:EMBEDDING_MAX_TEXT_CHARS] for row in batch]
        vectors = _embed_batch(embedding_provider, texts)
        index.store_vectors(
            model,
            {
                row.id: (row.content_hash, vector)
                for row, vector in zip(batch, vectors)
            },
        )

    try:
        query_vector = _embed_batch(embedding_provider, [query[:EMBEDDING_MAX_TEXT_CHARS]])[0]
    except MemorySemanticUnavailableError:
        raise
    hits = index.search_semantic(query_vector, model, max_rows=INDEX_MAX_ENTRIES)

    matches: list[dict[str, Any]] = []
    for row, similarity in hits:
        matches.append({
            "id": row.id[:128],
            "type": row.memory_type,
            "title": row.title[:256],
            "snippet": memory_snippet_text(str(redact_value(row.content)), ()),
            "score": similarity,
            "parent_id": row.parent_id if row.parent_id is None else str(row.parent_id)[:128],
            "source_ids": memory_source_ids(row),
        })
        if len(matches) >= limit:
            break
    return matches, {"vectors": len(hits), "entries": len(rows)}


def _embed_batch(embedding_provider: Any, texts: list[str]) -> list[list[float]]:
    try:
        return embedding_provider.embed_texts(texts)
    except EmbeddingProviderError as error:
        raise MemorySemanticUnavailableError(
            "embedding provider is unavailable"
        ) from error


def export_memory_entries_for_api(memory_store: Any) -> dict[str, Any]:
    """Export a bounded, lossless snapshot for memory migration.

    The records carry every authoritative field, so importing them into a
    fresh store reproduces the same entries, ids and metadata. Bounds come
    from the shared read-only snapshot budgets.
    """
    entries = load_memory_entries_for_api(memory_store, None)
    records = [
        {
            "id": entry.id,
            "type": entry.type.value,
            "title": entry.title,
            "content": entry.content,
            "metadata": entry.metadata,
            "tags": list(entry.tags),
            "created_at": entry.created_at,
            "last_accessed": entry.last_accessed,
            "access_count": entry.access_count,
            "importance": entry.importance,
            "token_count": entry.token_count,
            "compressed": entry.compressed,
            "parent_id": entry.parent_id,
        }
        for entry in entries
    ]
    return {"count": len(records), "entries": records}


def _entry_from_record(record: Any, position: int) -> MemoryEntry:
    """Build a validated MemoryEntry from one import record."""
    prefix = f"entry #{position}"
    if not isinstance(record, dict):
        raise MemoryTransferRequestError(f"{prefix} must be an object")
    entry_type = record.get("type", "user")
    if type(entry_type) is not str:
        raise MemoryTransferRequestError(f"{prefix} type must be a string")
    try:
        memory_type = MemoryType(entry_type)
    except ValueError as error:
        raise MemoryTransferRequestError(
            f"{prefix} has unknown memory type"
        ) from error
    title = record.get("title", "")
    if type(title) is not str or not title.strip():
        raise MemoryTransferRequestError(
            f"{prefix} title must be a non-empty string"
        )
    content = record.get("content", "")
    if type(content) is not str:
        raise MemoryTransferRequestError(f"{prefix} content must be a string")
    tags = record.get("tags", [])
    if type(tags) is not list or any(type(tag) is not str for tag in tags):
        raise MemoryTransferRequestError(
            f"{prefix} tags must be an array of strings"
        )
    metadata = record.get("metadata", {})
    if type(metadata) is not dict:
        raise MemoryTransferRequestError(f"{prefix} metadata must be an object")

    entry_id = record.get("id")
    if entry_id is not None and type(entry_id) is not str:
        raise MemoryTransferRequestError(f"{prefix} id must be a string")
    created_at = record.get("created_at")
    if created_at is None:
        created_at = datetime.now().isoformat()
    if type(created_at) is not str or not created_at:
        raise MemoryTransferRequestError(
            f"{prefix} created_at must be a non-empty string"
        )
    last_accessed = record.get("last_accessed")
    if last_accessed is None:
        last_accessed = created_at
    if type(last_accessed) is not str or not last_accessed:
        raise MemoryTransferRequestError(
            f"{prefix} last_accessed must be a non-empty string"
        )
    access_count = record.get("access_count", 0)
    if type(access_count) is not int or access_count < 0:
        raise MemoryTransferRequestError(
            f"{prefix} access_count must be a non-negative integer"
        )
    importance = record.get("importance", 0.5)
    if type(importance) not in (int, float):
        raise MemoryTransferRequestError(f"{prefix} importance must be a number")
    token_count = record.get("token_count", 0)
    if type(token_count) is not int or token_count < 0:
        raise MemoryTransferRequestError(
            f"{prefix} token_count must be a non-negative integer"
        )
    compressed = record.get("compressed", False)
    if type(compressed) is not bool:
        raise MemoryTransferRequestError(f"{prefix} compressed must be a boolean")
    parent_id = record.get("parent_id")
    if parent_id is not None and type(parent_id) is not str:
        raise MemoryTransferRequestError(
            f"{prefix} parent_id must be a string or null"
        )

    entry = MemoryEntry.create(
        memory_type,
        title,
        content,
        metadata=metadata,
        tags=tags,
        importance=importance,
    )
    if entry_id:
        entry.id = entry_id
    entry.created_at = created_at
    entry.last_accessed = last_accessed
    entry.access_count = access_count
    entry.importance = importance
    entry.token_count = token_count
    entry.compressed = compressed
    entry.parent_id = parent_id
    return entry


def import_memory_entries_for_api(
    memory_store: Any,
    payload: Any,
) -> dict[str, Any]:
    """Import records into the authoritative store with id-level dedup.

    Records whose id already exists (or repeats inside the batch) are
    skipped, so repeated imports are idempotent. Per-record failures are
    rejected without aborting the batch; every rejection is bounded and
    content-free.
    """
    if not isinstance(payload, dict):
        raise MemoryTransferRequestError("Memory import payload must be an object")
    records = payload.get("entries")
    if type(records) is not list:
        raise MemoryTransferRequestError(
            "Memory import payload must declare an entries list"
        )
    if len(records) > MEMORY_API_MAX_IMPORT_ENTRIES:
        raise MemoryTransferRequestError(
            "Memory import payload exceeds "
            f"{MEMORY_API_MAX_IMPORT_ENTRIES} entries per request"
        )

    existing = {
        entry.id for entry in load_memory_entries_for_api(memory_store, None)
    }
    imported = 0
    skipped = 0
    rejected = 0
    errors: list[str] = []
    seen: set[str] = set()
    for position, record in enumerate(records):
        try:
            entry = _entry_from_record(record, position)
        except MemoryTransferRequestError as error:
            rejected += 1
            if len(errors) < MEMORY_API_MAX_IMPORT_ERRORS:
                errors.append(str(error))
            continue
        if entry.id in existing or entry.id in seen:
            skipped += 1
            seen.add(entry.id)
            continue
        try:
            memory_store.store(entry)
        except (TypeError, ValueError, OSError) as error:
            rejected += 1
            if len(errors) < MEMORY_API_MAX_IMPORT_ERRORS:
                errors.append(f"entry #{position}: {error}"[:200])
            continue
        seen.add(entry.id)
        imported += 1
    return {
        "received": len(records),
        "imported": imported,
        "skipped": skipped,
        "rejected": rejected,
        "errors": errors,
    }


def _memory_backups_dir(memory_store: Any) -> Path:
    return Path(str(memory_store.memory_dir)) / BACKUPS_DIRNAME


def _canonical_payload_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _read_backup_envelope(path: Path) -> dict[str, Any] | None:
    """Read one backup envelope with integrity verification, or None."""
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if len(raw) > MEMORY_BACKUP_MAX_BYTES:
        return None
    try:
        envelope = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(envelope, dict):
        return None
    payload = envelope.get("payload")
    digest = envelope.get("payload_sha256")
    created_at = envelope.get("created_at")
    schema_version = envelope.get("schema_version")
    if (
        schema_version != BACKUP_SCHEMA_VERSION
        or not isinstance(payload, dict)
        or type(payload.get("entries")) is not list
        or type(digest) is not str
        or len(digest) != 64
        or type(created_at) is not str
        or not created_at
    ):
        return None
    intact = (
        hashlib.sha256(_canonical_payload_bytes(payload)).hexdigest() == digest
    )
    return {
        "created_at": created_at,
        "entries": len(payload["entries"]),
        "bytes": len(raw),
        "payload_sha256": digest,
        "intact": intact,
    }


def _prune_old_backups(backups_dir: Path, max_retained: int) -> list[str]:
    """Best-effort prune of the oldest backups beyond the retention cap.

    Names embed a microsecond creation stamp, so name order is creation
    order regardless of filesystem timestamp granularity.
    """
    try:
        names = sorted(
            name
            for name in os.listdir(backups_dir)
            if MEMORY_BACKUP_NAME_RE.fullmatch(name)
        )
    except OSError:
        return []
    pruned: list[str] = []
    for name in names[:-max_retained] if len(names) > max_retained else []:
        try:
            (backups_dir / name).unlink()
        except OSError:
            continue
        pruned.append(name)
    return pruned


def create_memory_backup_for_api(
    memory_store: Any,
    *,
    max_retained: int = MEMORY_BACKUP_MAX_RETAINED,
) -> dict[str, Any]:
    """Write a self-describing backup of the bounded export snapshot.

    The envelope embeds the SHA-256 of the canonically serialized payload,
    so every later restore verifies integrity without external metadata.
    Backups beyond ``max_retained`` are pruned oldest-first after the new
    file is durably in place.
    """
    if type(max_retained) is not int or not 1 <= max_retained <= 64:
        raise MemoryTransferRequestError(
            "Memory backup retention must be between 1 and 64"
        )
    payload = export_memory_entries_for_api(memory_store)
    created_at = datetime.now().isoformat(timespec="seconds")
    digest = hashlib.sha256(_canonical_payload_bytes(payload)).hexdigest()
    envelope = {
        "schema_version": BACKUP_SCHEMA_VERSION,
        "created_at": created_at,
        "payload_sha256": digest,
        "payload": payload,
    }
    body = (json.dumps(envelope, ensure_ascii=False) + "\n").encode("utf-8")
    if len(body) > MEMORY_BACKUP_MAX_BYTES:
        raise MemoryBackupFailedError(
            "memory backup exceeds the size budget"
        )

    backups_dir = _memory_backups_dir(memory_store)
    backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S%f")
    name = f"backup-{stamp}-{uuid.uuid4().hex[:8]}.json"
    target = backups_dir / name
    temporary = backups_dir / f"{name}.tmp"
    try:
        temporary.write_bytes(body)
        os.replace(temporary, target)
    except OSError as error:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise MemoryBackupFailedError(
            "memory backup could not be written"
        ) from error

    verified = _read_backup_envelope(target)
    if verified is None or not verified["intact"]:
        raise MemoryBackupFailedError(
            "memory backup failed its write-back verification"
        )

    pruned = _prune_old_backups(backups_dir, max_retained)
    return {
        "backup": name,
        "created_at": created_at,
        "entries": payload["count"],
        "bytes": len(body),
        "payload_sha256": digest,
        "pruned": pruned,
    }


def list_memory_backups_for_api(memory_store: Any) -> dict[str, Any]:
    """List existing backups, newest first, with integrity status."""
    backups_dir = _memory_backups_dir(memory_store)
    try:
        names = sorted(os.listdir(backups_dir))
    except OSError:
        names = []
    backups: list[dict[str, Any]] = []
    for name in names:
        if not MEMORY_BACKUP_NAME_RE.fullmatch(name):
            continue
        info = _read_backup_envelope(backups_dir / name)
        if info is None:
            continue
        backups.append({"name": name, **info})
    return {"backups": list(reversed(backups))}


def restore_memory_backup_for_api(
    memory_store: Any,
    payload: Any,
) -> dict[str, Any]:
    """Verify a named backup and merge it back through idempotent import."""
    if not isinstance(payload, dict):
        raise MemoryTransferRequestError("Memory restore payload must be an object")
    name = payload.get("backup")
    if (
        type(name) is not str
        or not MEMORY_BACKUP_NAME_RE.fullmatch(name)
    ):
        raise MemoryTransferRequestError(
            "Memory restore requires a valid backup name"
        )
    backups_dir = _memory_backups_dir(memory_store)
    target = backups_dir / name
    if target.resolve().parent != backups_dir.resolve():
        raise MemoryTransferRequestError(
            "Memory restore requires a valid backup name"
        )
    if not target.is_file():
        raise MemoryBackupNotFoundError(f"Unknown memory backup: {name}")
    try:
        raw = target.read_bytes()
    except OSError as error:
        raise MemoryBackupFailedError(
            "memory backup cannot be read"
        ) from error
    if len(raw) > MEMORY_BACKUP_MAX_BYTES:
        raise MemoryBackupFailedError(
            "memory backup exceeds the size budget"
        )
    try:
        stored = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise MemoryBackupFailedError(
            "memory backup cannot be read"
        ) from error
    payload = stored.get("payload") if isinstance(stored, dict) else None
    digest = stored.get("payload_sha256") if isinstance(stored, dict) else None
    if (
        not isinstance(payload, dict)
        or type(payload.get("entries")) is not list
        or type(digest) is not str
        or hashlib.sha256(_canonical_payload_bytes(payload)).hexdigest() != digest
    ):
        raise MemoryBackupFailedError(
            "memory backup failed its integrity check"
        )
    result = import_memory_entries_for_api(memory_store, payload)
    result["backup"] = name
    return result


def _parse_entry_timestamp(value: Any) -> "datetime | None":
    if type(value) is not str or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        return None
    return parsed


def prune_memory_entries_for_api(
    memory_store: MemoryRepository,
    payload: Any,
) -> dict[str, Any]:
    """Apply an explicit, bounded retention policy to the store.

    At least one criterion is required and the policy is opt-in per
    request: ``max_entries`` keeps the most valuable entries, while
    ``max_age_days`` and ``min_importance`` mark stale or lightweight
    entries. Integration probe entries are always excluded; entries with
    unparseable timestamps are kept. Deletion goes through the journalled
    ``delete`` path, at most 64 entries per request.
    """
    if not isinstance(payload, dict):
        raise MemoryTransferRequestError("Memory prune payload must be an object")
    unknown = sorted(set(payload) - MEMORY_PRUNE_ALLOWED_KEYS)
    if unknown:
        raise MemoryTransferRequestError(
            f"Memory prune payload has unknown fields: {', '.join(unknown)}"
        )
    max_entries = payload.get("max_entries")
    max_age_days = payload.get("max_age_days")
    min_importance = payload.get("min_importance")
    dry_run = payload.get("dry_run", False)
    if type(dry_run) is not bool:
        raise MemoryTransferRequestError("Memory prune dry_run must be a boolean")
    if max_entries is None and max_age_days is None and min_importance is None:
        raise MemoryTransferRequestError(
            "Memory prune requires at least one retention criterion"
        )
    if max_entries is not None and (
        type(max_entries) is not int
        or not 1 <= max_entries <= MEMORY_API_PRUNE_MAX_ENTRIES
    ):
        raise MemoryTransferRequestError(
            "Memory prune max_entries must be between 1 and "
            f"{MEMORY_API_PRUNE_MAX_ENTRIES}"
        )
    if max_age_days is not None and (
        type(max_age_days) is not int
        or not 1 <= max_age_days <= MEMORY_API_PRUNE_MAX_AGE_DAYS
    ):
        raise MemoryTransferRequestError(
            "Memory prune max_age_days must be between 1 and "
            f"{MEMORY_API_PRUNE_MAX_AGE_DAYS}"
        )
    if min_importance is not None and (
        type(min_importance) not in (int, float)
        or not 0 <= min_importance <= 1
    ):
        raise MemoryTransferRequestError(
            "Memory prune min_importance must be between 0 and 1"
        )

    entries = load_memory_entries_for_api(memory_store, None)
    manageable = [
        entry
        for entry in entries
        if MEMORY_PRUNE_EXCLUDED_METADATA_KEY not in entry.metadata
    ]
    victims: dict[tuple[str, str], Any] = {}

    if max_age_days is not None:
        cutoff = datetime.now() - timedelta(days=max_age_days)
        for entry in manageable:
            reference = _parse_entry_timestamp(
                entry.last_accessed
            ) or _parse_entry_timestamp(entry.created_at)
            if reference is None or reference >= cutoff:
                continue
            victims[(entry.type.value, entry.id)] = entry
    if min_importance is not None:
        for entry in manageable:
            if entry.importance < min_importance:
                victims[(entry.type.value, entry.id)] = entry
    if max_entries is not None:
        ranked = sorted(
            manageable,
            key=lambda item: (-item.importance, item.last_accessed, item.id),
        )
        keep = {
            (item.type.value, item.id) for item in ranked[:max_entries]
        }
        for entry in manageable:
            if (entry.type.value, entry.id) not in keep:
                victims[(entry.type.value, entry.id)] = entry

    ordered = sorted(
        victims.values(),
        key=lambda item: (item.importance, item.last_accessed, item.id),
    )
    bounded = ordered[:MEMORY_API_MAX_PRUNE_PER_REQUEST]
    result: dict[str, Any] = {
        "evaluated": len(entries),
        "matched": len(ordered),
        "candidates": [
            {"id": entry.id[:128], "type": entry.type.value}
            for entry in bounded
        ],
        "dry_run": dry_run,
        "pruned": [],
        "failed": [],
    }
    if dry_run:
        return result
    for entry in bounded:
        try:
            deleted = memory_store.delete(entry.type, entry.id)
        except OSError:
            deleted = False
        if deleted:
            result["pruned"].append(entry.id[:128])
        else:
            result["failed"].append(entry.id[:128])
    return result


__all__ = [
    "MEMORY_API_MAX_DIRECTORY_ENTRIES",
    "MEMORY_API_MAX_FILES",
    "MEMORY_API_MAX_FILE_BYTES",
    "MEMORY_API_MAX_TOTAL_BYTES",
    "MEMORY_API_MAX_TITLE_CHARS",
    "MEMORY_API_MAX_TIMESTAMP_CHARS",
    "MEMORY_API_MAX_TAGS",
    "MEMORY_API_MAX_TAG_CHARS",
    "MEMORY_API_DEFAULT_SEARCH_RESULTS",
    "MEMORY_API_MAX_SEARCH_RESULTS",
    "MEMORY_API_SEARCH_MODES",
    "INDEX_DB_FILENAME",
    "MemorySearchRequestError",
    "MemorySemanticUnavailableError",
    "MemoryTransferRequestError",
    "MemoryBackupNotFoundError",
    "MemoryBackupFailedError",
    "load_memory_entries_for_api",
    "public_memory_entry",
    "search_memory_entries_for_api",
    "close_memory_search_indexes",
    "export_memory_entries_for_api",
    "import_memory_entries_for_api",
    "create_memory_backup_for_api",
    "list_memory_backups_for_api",
    "restore_memory_backup_for_api",
    "prune_memory_entries_for_api",
]
