"""Shared bounded helpers for the standard-library and FastAPI memory APIs."""

from __future__ import annotations

from typing import Any

from core.brain.context_compressor import MemoryStore

MEMORY_API_MAX_DIRECTORY_ENTRIES = 8_192
MEMORY_API_MAX_FILES = 256
MEMORY_API_MAX_FILE_BYTES = 1024 * 1024
MEMORY_API_MAX_TOTAL_BYTES = 32 * 1024 * 1024
MEMORY_API_MAX_TITLE_CHARS = 512
MEMORY_API_MAX_TIMESTAMP_CHARS = 128
MEMORY_API_MAX_TAGS = 64
MEMORY_API_MAX_TAG_CHARS = 256


def load_memory_entries_for_api(
    memory_store: Any,
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


__all__ = [
    "MEMORY_API_MAX_DIRECTORY_ENTRIES",
    "MEMORY_API_MAX_FILES",
    "MEMORY_API_MAX_FILE_BYTES",
    "MEMORY_API_MAX_TOTAL_BYTES",
    "MEMORY_API_MAX_TITLE_CHARS",
    "MEMORY_API_MAX_TIMESTAMP_CHARS",
    "MEMORY_API_MAX_TAGS",
    "MEMORY_API_MAX_TAG_CHARS",
    "load_memory_entries_for_api",
    "public_memory_entry",
]
