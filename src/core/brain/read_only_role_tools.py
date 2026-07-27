"""Fixed read-only tools available only to production role Workers."""

from __future__ import annotations

import os
from pathlib import Path
import platform
import shutil
from collections.abc import Callable, Iterable
from itertools import islice
from typing import Any

from adapters.git_workspace import GitWorkspaceInspector
from core.contracts.role_tool_protocol import RoleToolBudget, RoleToolDefinition
from core.kernel.secret_redaction import redact_value

from .context_compressor import MemoryStore
from .role_registry import READ_ONLY_ROLE_TOOLS
from .role_tools import RoleToolBroker, RoleToolPolicy


MAX_DIRTY_PATHS = 50
MAX_MEMORY_RESULTS = 20
MAX_MEMORY_SNIPPET_CHARS = 512
MAX_MEMORY_DIRECTORY_ENTRIES = 256
MAX_MEMORY_FILES = 128
MAX_MEMORY_FILE_BYTES = 64 * 1024
MAX_MEMORY_TOTAL_BYTES = 512 * 1024
MAX_ROLE_NAMES = 50


def _object_schema(properties: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties or {},
        "additionalProperties": False,
    }


def _definitions() -> dict[str, RoleToolDefinition]:
    return {
        "system_status": RoleToolDefinition(
            "system_status",
            "Read bounded host and repository-volume status",
            _object_schema(),
        ),
        "model_list": RoleToolDefinition(
            "model_list",
            "List models from the trusted Ollama service",
            _object_schema({
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            }),
        ),
        "orchestrator_status": RoleToolDefinition(
            "orchestrator_status",
            "Read the trusted role registry and Worker isolation status",
            _object_schema(),
        ),
        "memory_search": RoleToolDefinition(
            "memory_search",
            "Search bounded entries in the trusted memory store",
            {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "maxLength": 256},
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": MAX_MEMORY_RESULTS,
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        ),
        "repository_metadata": RoleToolDefinition(
            "repository_metadata",
            "Read bounded Git metadata from the trusted repository",
            _object_schema(),
        ),
    }


def _redacted(handler: Callable[[dict[str, Any]], object]):
    def invoke(arguments: dict[str, Any]) -> object:
        return redact_value(handler(arguments))

    return invoke


def create_read_only_role_tool_broker(
    manager: object,
    memory_dir: str | Path,
    repository_root: str | Path,
    role_names: Iterable[str],
    budget: RoleToolBudget | None = None,
) -> RoleToolBroker:
    """Create the fixed catalog from trusted process-local dependencies."""
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
        query = arguments["query"].casefold()
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
            if query not in entry.title.casefold() and query not in entry.content.casefold():
                continue
            snippet = redact_value(entry.content)
            matches.append({
                "id": str(entry.id)[:128],
                "type": entry.type.value,
                "title": entry.title[:256],
                "snippet": str(snippet)[:MAX_MEMORY_SNIPPET_CHARS],
            })
            if len(matches) >= limit:
                break
        return {"results": matches}

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
        definitions=_definitions(),
        budget=budget,
    )
