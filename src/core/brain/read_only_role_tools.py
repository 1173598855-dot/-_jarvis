"""Fixed read-only tools available only to production role Workers."""

from __future__ import annotations

import os
import platform
import shutil
from collections.abc import Callable, Iterable
from itertools import islice
from pathlib import Path
from typing import Any

from adapters.git_workspace import GitWorkspaceInspector
from core.contracts.memory_search import (
    memory_matches,
    memory_query_terms,
    memory_score,
    memory_snippet_text,
    memory_source_ids,
)
from core.contracts.role_tool_catalog import (
    RoleToolAssembly,
    role_tool_definitions,
)
from core.contracts.role_tool_protocol import (
    RoleToolBudget,
    RoleToolProtocolError,
)
from core.kernel.secret_redaction import redact_value

from .context_compressor import MemoryStore
from .role_registry import READ_ONLY_ROLE_TOOLS
from .role_tools import RoleToolBroker, RoleToolPolicy

MAX_DIRTY_PATHS = 50
MAX_MEMORY_DIRECTORY_ENTRIES = 256
MAX_MEMORY_FILES = 128
MAX_MEMORY_FILE_BYTES = 64 * 1024
MAX_MEMORY_TOTAL_BYTES = 512 * 1024
MAX_ROLE_NAMES = 50


def _memory_query_terms(query: str) -> tuple[str, ...]:
    try:
        return memory_query_terms(query)
    except ValueError as error:
        raise RoleToolProtocolError(str(error)) from error


def _memory_snippet(entry: Any, terms: tuple[str, ...]) -> str:
    return memory_snippet_text(str(redact_value(entry.content)), terms)


def _redacted(handler: Callable[[dict[str, Any]], object]):
    def invoke(arguments: dict[str, Any]) -> object:
        return redact_value(handler(arguments))

    return invoke


def create_read_only_role_tool_broker(
    manager: object,
    memory_dir: str | Path,
    repository_root: str | Path,
    role_names: Iterable[str],
    assembly: RoleToolAssembly,
    budget: RoleToolBudget | None = None,
) -> RoleToolBroker:
    """Create the fixed catalog from trusted process-local dependencies."""
    if (
        not isinstance(assembly, RoleToolAssembly)
        or assembly != RoleToolAssembly.for_catalog()
    ):
        raise RoleToolProtocolError(
            "Role tool broker requires exact catalog assembly evidence"
        )
    list_models = getattr(manager, "list_models", None)
    if not callable(list_models):
        raise ValueError("trusted Ollama manager must support list_models")
    memory_root = Path(memory_dir).resolve()
    repository = Path(repository_root).resolve()
    if not repository.is_dir():
        raise ValueError("trusted repository root must be an existing directory")
    normalized_roles = tuple(sorted({
        name for name in role_names if isinstance(name, str) and name
    }))
    inspector = GitWorkspaceInspector(repository)

    def system_status(_arguments: dict[str, Any]) -> dict[str, Any]:
        disk = shutil.disk_usage(repository)
        return {
            "platform": platform.platform(),
            "cpu_count": os.cpu_count(),
            "disk": {
                "total": disk.total,
                "used": disk.used,
                "free": disk.free,
            },
        }

    def model_list(arguments: dict[str, Any]) -> dict[str, Any]:
        limit = arguments.get("limit", 20)
        models = list_models()
        bounded = []
        for model in islice(models, limit):
            bounded.append({
                "name": str(getattr(model, "name", ""))[:256],
                "size": getattr(model, "size", ""),
                "digest": str(getattr(model, "digest", ""))[:256],
                "modified_at": str(getattr(model, "modified_at", ""))[:128],
            })
        return {"models": bounded}

    def orchestrator_status(_arguments: dict[str, Any]) -> dict[str, Any]:
        return {
            "roles": list(normalized_roles[:MAX_ROLE_NAMES]),
            "worker_isolation": True,
        }

    def memory_search(arguments: dict[str, Any]) -> dict[str, Any]:
        terms = _memory_query_terms(arguments["query"])
        limit = arguments.get("limit", 10)
        store = MemoryStore(memory_dir=str(memory_root), read_only=True)
        matches = []
        entries = store.load(
            max_directory_entries=MAX_MEMORY_DIRECTORY_ENTRIES,
            max_files=MAX_MEMORY_FILES,
            max_file_bytes=MAX_MEMORY_FILE_BYTES,
            max_total_bytes=MAX_MEMORY_TOTAL_BYTES,
        )
        for entry in sorted(entries, key=lambda item: (item.title, item.id)):
            if not memory_matches(entry, terms):
                continue
            matches.append({
                "id": str(entry.id)[:128],
                "type": entry.type.value,
                "title": entry.title[:256],
                "snippet": _memory_snippet(entry, terms),
                "score": memory_score(entry, terms),
                "parent_id": entry.parent_id if entry.parent_id is None else str(entry.parent_id)[:128],
                "source_ids": memory_source_ids(entry),
            })
            if len(matches) >= limit:
                break
        ranked = sorted(matches, key=lambda item: (-item["score"], item["title"], item["id"]))
        return {"results": ranked}

    def repository_metadata(_arguments: dict[str, Any]) -> dict[str, Any]:
        snapshot = inspector.snapshot()
        return {
            "head": snapshot.head,
            "branch": snapshot.branch,
            "dirty_paths": list(snapshot.dirty_paths[:MAX_DIRTY_PATHS]),
        }

    handlers = {
        "system_status": _redacted(system_status),
        "model_list": _redacted(model_list),
        "orchestrator_status": _redacted(orchestrator_status),
        "memory_search": _redacted(memory_search),
        "repository_metadata": _redacted(repository_metadata),
    }
    grants = {
        role_name: READ_ONLY_ROLE_TOOLS.get(role_name, ())
        for role_name in normalized_roles
    }
    return RoleToolBroker(
        policy=RoleToolPolicy(grants),
        handlers=handlers,
        definitions=role_tool_definitions(),
        budget=budget,
    )
