"""MemoryRepository port for swappable memory storage (Phase F).

The port freezes the bounded storage surface that the app layer and role
tools consume, so a file, SQLite or vector-backed implementation can be
swapped in at the composition root without touching consumers. The Markdown
``MemoryStore`` is the reference implementation and the files under its
memory directory remain the single authoritative source; every other
storage shape is derived or secondary.

The port is structural (``typing.Protocol``) on purpose: the hardened
reference store predates the port and must not change shape to conform.
:func:`check_memory_repository_conformance` is the unified extension
contract test from the development guide — any implementation must pass it
before it is registered.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol, runtime_checkable

MEMORY_REPOSITORY_PORT_ID = "memory-repository"
# Version 2 adds the journalled ``delete`` used by retention policies.
MEMORY_REPOSITORY_PORT_VERSION = 2


@runtime_checkable
class MemoryRepository(Protocol):
    """Structural port implemented by memory storage backends."""

    read_only: bool
    memory_dir: Path

    def load(
        self,
        memory_type: Optional[Any] = None,
        *,
        max_directory_entries: Optional[int] = None,
        max_files: Optional[int] = None,
        max_file_bytes: Optional[int] = None,
        max_total_bytes: Optional[int] = None,
    ) -> List[Any]:
        """Load entries; read-only instances accept bounded budgets."""
        ...

    def store(self, entry: Any) -> str:
        """Persist one entry and return its storage path."""
        ...

    def delete(self, memory_type: Any, entry_id: str) -> bool:
        """Delete one entry by type and id through the journalled path.

        Implementations may refuse lifecycle-protected entries; read-only
        repositories must refuse deletion entirely.
        """
        ...

    def get_stats(self) -> Dict[str, Any]:
        """Return bounded storage statistics."""
        ...


def check_memory_repository_conformance(
    repository: MemoryRepository,
    *,
    entry_factory: Callable[[int], Any],
) -> None:
    """Unified extension contract test for MemoryRepository implementations.

    Raises ``AssertionError`` with a specific message when the repository
    violates the port. The entry factory must return a fresh, valid entry
    per call whose id is unique across calls. Writable repositories verify
    the full store/load round trip; read-only repositories verify bounded
    loads, statistics and the write refusal.
    """
    assert isinstance(repository, MemoryRepository), (
        "repository does not satisfy the MemoryRepository protocol"
    )
    assert type(repository.read_only) is bool, "read_only must be a bool"
    assert isinstance(repository.memory_dir, Path), (
        "memory_dir must be a Path"
    )
    if repository.read_only:
        _check_read_only_repository(repository, entry_factory)
    else:
        _check_writable_repository(repository, entry_factory)


def _check_writable_repository(
    repository: MemoryRepository,
    entry_factory: Callable[[int], Any],
) -> None:
    entry = entry_factory(0)
    path = repository.store(entry)
    assert isinstance(path, str) and path, "store must return a storage path"

    loaded = repository.load()
    assert any(
        candidate.id == entry.id and candidate.content == entry.content
        for candidate in loaded
    ), "stored entry must round trip through load"

    reloaded = repository.load()
    assert len(reloaded) == len(loaded), "load must be deterministic"

    assert repository.delete(entry.type, entry.id) is True, (
        "writable repositories must delete a stored entry by type and id"
    )
    after_delete = repository.load()
    assert all(
        candidate.id != entry.id for candidate in after_delete
    ), "deleted entries must disappear from load"

    stats = repository.get_stats()
    assert isinstance(stats, dict), "get_stats must return a dict"
    assert "total" in stats, "get_stats must report the entry total"

    try:
        repository.load(max_files=1)
    except Exception:
        pass
    else:
        raise AssertionError(
            "writable repositories must refuse read-only budget kwargs"
        )


def _check_read_only_repository(
    repository: MemoryRepository,
    entry_factory: Callable[[int], Any],
) -> None:
    loaded = repository.load(
        max_directory_entries=256,
        max_files=128,
        max_file_bytes=64 * 1024,
        max_total_bytes=512 * 1024,
    )
    assert isinstance(loaded, list), "load must return a list"

    reloaded = repository.load(
        max_directory_entries=256,
        max_files=128,
        max_file_bytes=64 * 1024,
        max_total_bytes=512 * 1024,
    )
    assert len(reloaded) == len(loaded), "load must be deterministic"

    bounded = repository.load(
        max_directory_entries=256,
        max_files=1,
        max_file_bytes=64 * 1024,
        max_total_bytes=512 * 1024,
    )
    assert len(bounded) <= 1, "read-only loads must honor max_files"

    stats = repository.get_stats()
    assert isinstance(stats, dict), "get_stats must return a dict"
    assert "total" in stats, "get_stats must report the entry total"

    try:
        repository.store(entry_factory(1))
    except Exception:
        pass
    else:
        raise AssertionError("read-only repositories must refuse store()")
    try:
        repository.delete(None, "nonexistent0")
    except Exception:
        pass
    else:
        raise AssertionError("read-only repositories must refuse delete()")


__all__ = [
    "MEMORY_REPOSITORY_PORT_ID",
    "MEMORY_REPOSITORY_PORT_VERSION",
    "MemoryRepository",
    "check_memory_repository_conformance",
]
