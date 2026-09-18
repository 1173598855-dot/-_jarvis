"""Parent-owned, default-deny capability broker for plugin workers."""

from __future__ import annotations

import functools
import json
import math
import os
import re
import stat
import threading
from collections import deque
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any
from urllib.parse import urljoin, urlsplit

from core.contracts.plugin_worker_protocol import (
    PluginBrokerRequest,
    PluginBrokerResult,
    PluginWorkerProtocolError,
    bounded_stable_json_size,
    stable_json_bytes,
)

from .event_bus import Event, EventBus

MAX_BROKER_CALLS = 32
MAX_BROKER_EXCHANGE_BYTES = 65_536
MAX_PLUGIN_EVENT_PAYLOAD_BYTES = 16 * 1024
EVENT_EMIT_CAPABILITY = "event.emit"
SYSTEM_STATS_CAPABILITY = "system.stats"
SYSTEM_MONITOR_PERMISSION = "system_monitor"
FILE_READ_CAPABILITY = "file.read"
FILE_READ_PERMISSION = "file_read"
FILE_READ_DENIED_REASON = "file_read_denied"
MAX_FILE_READ_BYTES = 1024 * 1024
FILE_LIST_CAPABILITY = "file.list"
FILE_LIST_PERMISSION = FILE_READ_PERMISSION
FILE_LIST_DENIED_REASON = "file_list_denied"
MAX_FILE_LIST_ENTRIES = 8_192
CONFIG_GET_CAPABILITY = "config.get"
CONFIG_GET_PERMISSION = "system_config"
CONFIG_GET_DENIED_REASON = "config_get_denied"
PLUGIN_CONFIG_FILE = "config.json"
MAX_PLUGIN_CONFIG_BYTES = 64 * 1024
LLM_CALL_CAPABILITY = "llm.call"
LLM_CALL_PERMISSION = "llm_access"
LLM_CALL_DENIED_REASON = "llm_call_denied"
MAX_LLM_PROMPT_BYTES = 32 * 1024
NETWORK_GET_CAPABILITY = "network.get"
NETWORK_GET_PERMISSION = "network"
NETWORK_GET_DENIED_REASON = "network_get_denied"
MAX_NETWORK_URL_BYTES = 2048
MAX_NETWORK_BODY_BYTES = 32 * 1024
MAX_NETWORK_HEADERS = 64
MAX_NETWORK_HEADER_BYTES = 8 * 1024
MAX_NETWORK_REDIRECTS = 3
NETWORK_TIMEOUT_SECONDS = 5.0
MAX_SYSTEM_STATS_INTERFACES = 64
MANIFEST_PERMISSION_BY_CAPABILITY = MappingProxyType(
    {
        EVENT_EMIT_CAPABILITY: "event_bus",
        SYSTEM_STATS_CAPABILITY: SYSTEM_MONITOR_PERMISSION,
        FILE_READ_CAPABILITY: FILE_READ_PERMISSION,
        FILE_LIST_CAPABILITY: FILE_LIST_PERMISSION,
        CONFIG_GET_CAPABILITY: CONFIG_GET_PERMISSION,
        LLM_CALL_CAPABILITY: LLM_CALL_PERMISSION,
        NETWORK_GET_CAPABILITY: NETWORK_GET_PERMISSION,
    }
)
FIRST_PARTY_EVENT_GRANTS = MappingProxyType(
    {
        "event-logger": frozenset({EVENT_EMIT_CAPABILITY}),
        "plugin-template": frozenset({EVENT_EMIT_CAPABILITY}),
    }
)


def _empty_process_snapshot() -> dict[str, Any]:
    return {
        "pid": 0,
        "cpu_percent": 0.0,
        "memory_percent": 0.0,
        "memory_info": {"rss": 0, "vms": 0},
    }


def _empty_system_stats_snapshot() -> dict[str, Any]:
    return {
        "cpu": {"usage": 0, "cores": 0, "model": "N/A"},
        "memory": {"total": 0, "used": 0, "free": 0, "usage": 0},
        "disk": {"total": 0, "used": 0, "free": 0, "usage": 0},
        "network": {"interfaces": []},
        "process": _empty_process_snapshot(),
    }


def _process_sample(psutil_module: Any) -> dict[str, Any]:
    try:
        process = psutil_module.Process()
        memory_info = process.memory_info()
        return {
            "pid": int(process.pid),
            "cpu_percent": float(process.cpu_percent(interval=None)),
            "memory_percent": float(process.memory_percent()),
            "memory_info": {
                "rss": int(getattr(memory_info, "rss", 0)),
                "vms": int(getattr(memory_info, "vms", 0)),
            },
        }
    except Exception:
        return _empty_process_snapshot()


def collect_system_stats_snapshot() -> dict[str, Any]:
    """Return a bounded read-only cpu, memory, disk, network and process snapshot."""
    try:
        import psutil
    except ImportError:
        return _empty_system_stats_snapshot()
    cpu_percent = psutil.cpu_percent(interval=0.1)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    interfaces = sorted(
        (
            {"name": iface, "ip": address.address, "status": "up"}
            for iface, addresses in psutil.net_if_addrs().items()
            for address in addresses
            if getattr(address, "family", None) == 2
        ),
        key=lambda entry: (entry["name"], entry["ip"]),
    )[:MAX_SYSTEM_STATS_INTERFACES]
    return {
        "cpu": {
            "usage": float(cpu_percent),
            "cores": int(psutil.cpu_count() or 0),
            "model": "Unknown",
        },
        "memory": {
            "total": int(memory.total),
            "used": int(memory.used),
            "free": int(memory.free),
            "usage": float(memory.percent),
        },
        "disk": {
            "total": int(disk.total),
            "used": int(disk.used),
            "free": int(disk.free),
            "usage": float(disk.percent),
        },
        "network": {"interfaces": interfaces},
        "process": _process_sample(psutil),
    }


def _is_link_or_reparse(path: Path) -> bool:
    """True for symlinks and Windows reparse points such as junctions."""
    try:
        details = path.lstat()
    except (OSError, ValueError):
        return True
    return _is_reparse_stat(details)


def _is_reparse_stat(details: os.stat_result) -> bool:
    """True for a symlink or a platform reparse-point stat result."""
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(
        stat.S_ISLNK(details.st_mode)
        or getattr(details, "st_file_attributes", 0) & reparse_flag
    )


def _resolve_file_rooted_path(
    file_root: Path, path_value: str, denied_reason: str
) -> tuple[Path, tuple[str, ...]]:
    """Resolve a relative path while rejecting traversal and linked components."""
    try:
        requested = Path(path_value)
        if (
            requested.is_absolute()
            or requested.drive
            or requested.root
            or any(part == ".." for part in requested.parts)
        ):
            raise PluginCapabilityDenied(denied_reason)
        current = file_root
        for part in requested.parts:
            current = current / part
            if _is_link_or_reparse(current):
                raise PluginCapabilityDenied(denied_reason)
        resolved = current.resolve(strict=True)
        if file_root != resolved and file_root not in resolved.parents:
            raise PluginCapabilityDenied(denied_reason)
    except PluginCapabilityDenied:
        raise
    except (OSError, RuntimeError, ValueError):
        raise PluginCapabilityDenied(denied_reason) from None
    return resolved, requested.parts


def _supports_no_follow_directory_scan() -> bool:
    """Whether directory traversal can use descriptor-relative no-follow opens."""
    return (
        os.name != "nt"
        and hasattr(os, "O_DIRECTORY")
        and hasattr(os, "O_NOFOLLOW")
        and os.open in os.supports_dir_fd
        and os.scandir in os.supports_fd
    )


def _supports_no_follow_file_open() -> bool:
    """Whether rooted file opens can use descriptor-relative no-follow flags."""
    return (
        os.name != "nt"
        and hasattr(os, "O_DIRECTORY")
        and hasattr(os, "O_NOFOLLOW")
        and os.open in os.supports_dir_fd
        and os.stat in os.supports_dir_fd
        and os.stat in os.supports_follow_symlinks
    )


def _directory_identity(details: os.stat_result) -> tuple[int, int, int]:
    """Return fields that identify one directory across a scan."""
    return (
        int(getattr(details, "st_dev", 0)),
        int(getattr(details, "st_ino", 0)),
        int(getattr(details, "st_file_attributes", 0)),
    )


def _same_file(left: os.stat_result, right: os.stat_result) -> bool:
    """Compare the stable identity fields exposed by local stat results."""
    return (
        int(getattr(left, "st_dev", 0)),
        int(getattr(left, "st_ino", 0)),
    ) == (
        int(getattr(right, "st_dev", 0)),
        int(getattr(right, "st_ino", 0)),
    )


def _file_list_entry_type(entry: os.DirEntry[str]) -> str:
    """Classify one direct child using no-follow metadata."""
    name = entry.name
    if not isinstance(name, str):
        raise PluginCapabilityDenied(FILE_LIST_DENIED_REASON)
    try:
        name.encode("utf-8")
        details = entry.stat(follow_symlinks=False)
    except (OSError, UnicodeEncodeError, ValueError):
        raise PluginCapabilityDenied(FILE_LIST_DENIED_REASON) from None
    if _is_reparse_stat(details):
        return "link"
    if stat.S_ISREG(details.st_mode):
        return "file"
    if stat.S_ISDIR(details.st_mode):
        return "directory"
    return "other"

_PLUGIN_EVENT_TYPE = re.compile(r"^plugin\.[A-Za-z0-9][A-Za-z0-9._:-]{0,95}$")
_PLUGIN_CONFIG_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_LLM_MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+-]{0,127}$")
_NETWORK_HOST = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._:-]{0,251}[A-Za-z0-9])?$")
_ROOTED_CAPABILITY_HANDLERS = MappingProxyType(
    {
        FILE_READ_CAPABILITY: (
            "_file_read_registered",
            "_file_read_handler",
            FILE_READ_DENIED_REASON,
        ),
        FILE_LIST_CAPABILITY: (
            "_file_list_registered",
            "_file_list_handler",
            FILE_LIST_DENIED_REASON,
        ),
        CONFIG_GET_CAPABILITY: (
            "_config_registered",
            "_config_get_handler",
            CONFIG_GET_DENIED_REASON,
        ),
    }
)

PluginCapabilityHandler = Callable[[Mapping[str, Any]], Any]


class PluginCapabilityDenied(PluginWorkerProtocolError):
    """A parent-owned handler's stable, policy-level denial."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"capability denied: {reason}")
        self.reason = reason


def _validate_network_url(raw_url: str) -> tuple[str, str]:
    """Return the (scheme, host) pair of one strict http(s) URL."""
    if not isinstance(raw_url, str) or not raw_url:
        raise PluginCapabilityDenied(NETWORK_GET_DENIED_REASON)
    try:
        raw_bytes = raw_url.encode("utf-8")
    except UnicodeEncodeError:
        raise PluginCapabilityDenied(NETWORK_GET_DENIED_REASON) from None
    if len(raw_bytes) > MAX_NETWORK_URL_BYTES:
        raise PluginCapabilityDenied(NETWORK_GET_DENIED_REASON)
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in raw_url):
        raise PluginCapabilityDenied(NETWORK_GET_DENIED_REASON)
    try:
        parsed = urlsplit(raw_url)
        scheme = parsed.scheme.lower()
        host = parsed.hostname
        _ = parsed.port
    except ValueError:
        raise PluginCapabilityDenied(NETWORK_GET_DENIED_REASON) from None
    if scheme not in {"http", "https"}:
        raise PluginCapabilityDenied(NETWORK_GET_DENIED_REASON)
    if parsed.username is not None or parsed.password is not None:
        raise PluginCapabilityDenied(NETWORK_GET_DENIED_REASON)
    if isinstance(host, str) and _NETWORK_HOST.fullmatch(host):
        return scheme, host
    raise PluginCapabilityDenied(NETWORK_GET_DENIED_REASON)


def _network_build_headers(response: Any) -> dict[str, str]:
    """Copy the response headers into a bounded lowercase map."""
    headers: dict[str, str] = {}
    header_bytes = 0
    for name, value in response.headers.items():
        if not isinstance(name, str) or not isinstance(value, str):
            raise PluginCapabilityDenied(NETWORK_GET_DENIED_REASON)
        if len(headers) >= MAX_NETWORK_HEADERS:
            raise PluginCapabilityDenied(NETWORK_GET_DENIED_REASON)
        if not name.strip():
            continue
        normalized = name.lower()
        size = len(normalized.encode("utf-8")) + len(value.encode("utf-8")) + 2
        if header_bytes + size > MAX_NETWORK_HEADER_BYTES:
            raise PluginCapabilityDenied(NETWORK_GET_DENIED_REASON)
        header_bytes += size
        headers[normalized] = value
    return headers


def _network_read_body(response: Any, requests: Any) -> str:
    """Read at most the bounded body budget and decode strict UTF-8."""
    content_length = response.headers.get("Content-Length")
    if (
        isinstance(content_length, str)
        and content_length.isdigit()
        and int(content_length) > MAX_NETWORK_BODY_BYTES
    ):
        raise PluginCapabilityDenied(NETWORK_GET_DENIED_REASON)
    raw = bytearray()
    try:
        for chunk in response.iter_content(chunk_size=4096):
            if chunk is None:
                continue
            if isinstance(chunk, str):
                chunk = chunk.encode("utf-8")
            elif not isinstance(chunk, (bytes, bytearray, memoryview)):
                raise PluginCapabilityDenied(NETWORK_GET_DENIED_REASON)
            raw.extend(chunk)
            if len(raw) > MAX_NETWORK_BODY_BYTES:
                raise PluginCapabilityDenied(NETWORK_GET_DENIED_REASON)
    except PluginCapabilityDenied:
        raise
    except Exception:
        raise PluginCapabilityDenied(NETWORK_GET_DENIED_REASON) from None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        raise PluginCapabilityDenied(NETWORK_GET_DENIED_REASON) from None


def _network_get_response(response: Any, requests: Any) -> dict[str, Any]:
    """Return the bounded status, header and body snapshot of one response."""
    status = getattr(response, "status_code", None)
    if type(status) is not int:
        raise PluginCapabilityDenied(NETWORK_GET_DENIED_REASON)
    return {
        "status": status,
        "headers": _network_build_headers(response),
        "body": _network_read_body(response, requests),
    }


@dataclass(frozen=True, slots=True)
class PluginBrokerAuditEntry:
    """Bounded, payload-free evidence for one broker decision."""

    request_id: str
    call_id: str
    plugin_id: str
    capability: str
    allowed: bool
    reason: str
    argument_bytes: int


class PluginBroker:
    """Authorize explicit plugin capabilities for parent-owned handling."""

    def __init__(
        self,
        event_bus: EventBus,
        grants: Mapping[str, Iterable[str]] | None = None,
        audit_limit: int = 256,
    ) -> None:
        if not isinstance(event_bus, EventBus):
            raise ValueError("event_bus must be an EventBus")
        if type(audit_limit) is not int or audit_limit < 1:
            raise ValueError("audit_limit must be a positive integer")
        self._event_bus = event_bus
        self._grants = self._normalize_grants(grants)
        self._handlers: dict[str, PluginCapabilityHandler] = {}
        self._file_read_roots: dict[str, Path] = {}
        self._file_read_registered = False
        self._file_list_registered = False
        self._config_registered = False
        self._llm_provider: Callable[[str, str], Any] | None = None
        self._network_get_hosts: frozenset[str] = frozenset()
        self._audit: deque[PluginBrokerAuditEntry] = deque(maxlen=audit_limit)
        self._active_generations: dict[str, int] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _normalize_grants(
        grants: Mapping[str, Iterable[str]] | None,
    ) -> Mapping[str, frozenset[str]]:
        if grants is None:
            return MappingProxyType({})
        if not isinstance(grants, Mapping):
            raise ValueError("grants must map plugin identifiers to capabilities")
        normalized: dict[str, frozenset[str]] = {}
        for plugin_id, capabilities in grants.items():
            if not isinstance(plugin_id, str) or not plugin_id:
                raise ValueError("grant plugin identifiers must be non-empty strings")
            try:
                capability_set = frozenset(capabilities)
            except TypeError as error:
                raise ValueError("grant capabilities must be iterable strings") from error
            if any(
                not isinstance(capability, str) or not capability
                for capability in capability_set
            ):
                raise ValueError("grant capabilities must be non-empty strings")
            normalized[plugin_id] = capability_set
        return MappingProxyType(normalized)

    def begin_lifecycle(
        self,
        plugin_id: str,
        request_id: str,
        declared_permissions: Iterable[str],
        generation: int,
        *,
        deadline: float | None = None,
    ) -> PluginBrokerSession:
        if not isinstance(plugin_id, str) or not plugin_id:
            raise ValueError("plugin_id must be a non-empty string")
        if not isinstance(request_id, str) or not request_id:
            raise ValueError("request_id must be a non-empty string")
        if type(generation) is not int or generation < 1:
            raise ValueError("generation must be a positive integer")
        if deadline is not None and (
            isinstance(deadline, bool)
            or not isinstance(deadline, (int, float))
            or not math.isfinite(deadline)
        ):
            raise ValueError("deadline must be a finite absolute time")
        try:
            declared = frozenset(declared_permissions)
        except TypeError as error:
            raise ValueError("declared_permissions must be iterable strings") from error
        if any(
            not isinstance(permission, str) or not permission for permission in declared
        ):
            raise ValueError("declared_permissions must contain non-empty strings")
        with self._lock:
            active_generation = self._active_generations.get(plugin_id)
            if active_generation is not None and generation < active_generation:
                raise ValueError("generation must not replace a newer lifecycle")
            self._active_generations[plugin_id] = generation
        return PluginBrokerSession(
            self, plugin_id, request_id, declared, generation, deadline
        )

    def register_handler(
        self, capability: str, handler: PluginCapabilityHandler
    ) -> None:
        if capability not in MANIFEST_PERMISSION_BY_CAPABILITY:
            raise ValueError("capability is not supported by the V1 broker")
        if not callable(handler):
            raise ValueError("handler must be callable")
        with self._lock:
            self._handlers[capability] = handler

    def register_event_emit_handler(self) -> None:
        """Register the parent-owned V1 event staging handler."""
        self.register_handler(EVENT_EMIT_CAPABILITY, self._emit_plugin_event)

    def register_system_stats_handler(self) -> None:
        """Register the parent-owned read-only system stats handler."""
        self.register_handler(
            SYSTEM_STATS_CAPABILITY, self._system_stats_handler
        )

    def register_file_read_handler(self) -> None:
        """Enable the parent-owned read-only file.read capability."""
        with self._lock:
            self._file_read_registered = True

    def register_file_list_handler(self) -> None:
        """Enable the parent-owned read-only file.list capability."""
        with self._lock:
            self._file_list_registered = True

    def register_config_get_handler(self) -> None:
        """Enable the parent-owned read-only config.get capability."""
        with self._lock:
            self._config_registered = True

    def register_llm_call_handler(
        self, provider: Callable[[str, str], Any]
    ) -> None:
        """Enable the parent-owned llm.call capability with one provider."""
        if not callable(provider):
            raise ValueError("provider must be callable")
        with self._lock:
            self._llm_provider = provider
        self.register_handler(LLM_CALL_CAPABILITY, self._llm_call_handler)

    def register_network_get_handler(self, hosts: Iterable[str]) -> None:
        """Enable the parent-owned network.get capability with a host allowlist."""
        if isinstance(hosts, str):
            raise ValueError("hosts must be an iterable of strings")
        allowlist: set[str] = set()
        try:
            host_items = tuple(hosts)
        except TypeError as error:
            raise ValueError("hosts must be an iterable of strings") from error
        for host in host_items:
            if type(host) is not str or not host or len(host) > 253:
                raise ValueError("host allowlist entries must be valid hostnames")
            if not _NETWORK_HOST.fullmatch(host):
                raise ValueError("host allowlist entries must be valid hostnames")
            allowlist.add(host)
        with self._lock:
            self._network_get_hosts = frozenset(allowlist)
        self.register_handler(NETWORK_GET_CAPABILITY, self._network_get_handler)

    def bind_file_read_root(self, plugin_id: str, file_root: str | Path) -> None:
        """Bind one plugin's read-only fence to its validated plugin root."""
        if not isinstance(plugin_id, str) or not plugin_id:
            raise ValueError("plugin_id must be a non-empty string")
        resolved = Path(file_root).resolve(strict=True)
        if not resolved.is_dir():
            raise ValueError("file root must be a directory")
        with self._lock:
            self._file_read_roots[plugin_id] = resolved

    def _file_root_for(self, plugin_id: str) -> Path | None:
        with self._lock:
            return self._file_read_roots.get(plugin_id)

    def audit_log(self) -> list[PluginBrokerAuditEntry]:
        """Return a copy of bounded decision evidence without plugin payloads."""
        with self._lock:
            return list(self._audit)

    def _is_active_generation(self, plugin_id: str, generation: int) -> bool:
        with self._lock:
            return self._active_generations.get(plugin_id) == generation

    def _handler_for(self, capability: str) -> PluginCapabilityHandler | None:
        with self._lock:
            return self._handlers.get(capability)

    def _record(
        self,
        request: PluginBrokerRequest,
        allowed: bool,
        reason: str,
        argument_bytes: int,
    ) -> None:
        entry = PluginBrokerAuditEntry(
            request_id=request.request_id,
            call_id=request.call_id,
            plugin_id=request.plugin_id,
            capability=request.capability,
            allowed=allowed,
            reason=reason,
            argument_bytes=argument_bytes,
        )
        with self._lock:
            self._audit.append(entry)

    def _emit_plugin_event(self, arguments: Mapping[str, Any]) -> dict[str, bool]:
        self._validate_event_arguments(arguments)
        return {"published": True}

    def _system_stats_handler(
        self, arguments: Mapping[str, Any]
    ) -> dict[str, Any]:
        if arguments:
            raise PluginWorkerProtocolError(
                "system.stats arguments must be an empty object"
            )
        return collect_system_stats_snapshot()

    def _file_read_handler(
        self, file_root: Path, arguments: Mapping[str, Any]
    ) -> str:
        if not isinstance(arguments, Mapping) or set(arguments) != {"path"}:
            raise PluginWorkerProtocolError(
                "file.read arguments must contain exactly path"
            )
        path_value = arguments["path"]
        if not isinstance(path_value, str) or not path_value:
            raise PluginWorkerProtocolError(
                "file.read path must be a non-empty string"
            )
        resolved, path_parts = _resolve_file_rooted_path(
            file_root, path_value, FILE_READ_DENIED_REASON
        )
        if not path_parts:
            raise PluginCapabilityDenied(FILE_READ_DENIED_REASON)
        descriptors: list[int] = []
        try:
            expected_stat = resolved.lstat()
            if (
                not stat.S_ISREG(expected_stat.st_mode)
                or _is_reparse_stat(expected_stat)
            ):
                raise PluginCapabilityDenied(FILE_READ_DENIED_REASON)
            if _supports_no_follow_file_open():
                directory_flags = (
                    os.O_RDONLY
                    | os.O_DIRECTORY
                    | os.O_NOFOLLOW
                    | getattr(os, "O_CLOEXEC", 0)
                )
                file_flags = (
                    os.O_RDONLY
                    | os.O_NOFOLLOW
                    | getattr(os, "O_CLOEXEC", 0)
                )
                current_fd = os.open(file_root, directory_flags)
                descriptors.append(current_fd)
                for part in path_parts[:-1]:
                    if part == ".":
                        continue
                    current_fd = os.open(
                        part, directory_flags, dir_fd=current_fd
                    )
                    descriptors.append(current_fd)
                descriptor = os.open(
                    path_parts[-1], file_flags, dir_fd=current_fd
                )
                parent_fd = current_fd
            else:
                descriptor = os.open(
                    resolved,
                    os.O_RDONLY | getattr(os, "O_BINARY", 0),
                )
                parent_fd = None
            descriptors.append(descriptor)
            opened_stat = os.fstat(descriptor)
            if (
                not stat.S_ISREG(opened_stat.st_mode)
                or _is_reparse_stat(opened_stat)
                or not _same_file(expected_stat, opened_stat)
                or opened_stat.st_size > MAX_FILE_READ_BYTES
            ):
                raise PluginCapabilityDenied(FILE_READ_DENIED_REASON)
            chunks: list[bytes] = []
            total = 0
            while total <= MAX_FILE_READ_BYTES:
                chunk = os.read(
                    descriptor,
                    min(64 * 1024, MAX_FILE_READ_BYTES + 1 - total),
                )
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                if total > MAX_FILE_READ_BYTES:
                    raise PluginCapabilityDenied(FILE_READ_DENIED_REASON)
            final_opened_stat = os.fstat(descriptor)
            if (
                final_opened_stat.st_size != opened_stat.st_size
                or not _same_file(opened_stat, final_opened_stat)
                or total != opened_stat.st_size
            ):
                raise PluginCapabilityDenied(FILE_READ_DENIED_REASON)
            if parent_fd is None:
                final_path_stat = resolved.lstat()
            else:
                final_path_stat = os.stat(
                    path_parts[-1],
                    dir_fd=parent_fd,
                    follow_symlinks=False,
                )
            if (
                not stat.S_ISREG(final_path_stat.st_mode)
                or _is_reparse_stat(final_path_stat)
                or not _same_file(opened_stat, final_path_stat)
            ):
                raise PluginCapabilityDenied(FILE_READ_DENIED_REASON)
            raw = b"".join(chunks)
        except PluginCapabilityDenied:
            raise
        except (OSError, ValueError):
            raise PluginCapabilityDenied(FILE_READ_DENIED_REASON) from None
        finally:
            for descriptor in reversed(descriptors):
                try:
                    os.close(descriptor)
                except OSError:
                    pass
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            raise PluginCapabilityDenied(FILE_READ_DENIED_REASON) from None

    def _file_list_handler(
        self, file_root: Path, arguments: Mapping[str, Any]
    ) -> list[dict[str, str]]:
        """Return a bounded direct-child snapshot within one plugin root."""
        if not isinstance(arguments, Mapping) or set(arguments) != {"path"}:
            raise PluginWorkerProtocolError(
                "file.list arguments must contain exactly path"
            )
        path_value = arguments["path"]
        if not isinstance(path_value, str) or not path_value:
            raise PluginWorkerProtocolError(
                "file.list path must be a non-empty string"
            )
        resolved, path_parts = _resolve_file_rooted_path(
            file_root, path_value, FILE_LIST_DENIED_REASON
        )
        try:
            details = resolved.lstat()
            if not stat.S_ISDIR(details.st_mode) or _is_reparse_stat(details):
                raise PluginCapabilityDenied(FILE_LIST_DENIED_REASON)
            if _supports_no_follow_directory_scan():
                snapshot = self._scan_file_list_no_follow(
                    file_root, path_parts, _directory_identity(details)
                )
            else:
                before = _directory_identity(details)
                snapshot = self._scan_file_list_path(resolved)
                after = _directory_identity(resolved.lstat())
                if before != after:
                    raise PluginCapabilityDenied(FILE_LIST_DENIED_REASON)
        except PluginCapabilityDenied:
            raise
        except (OSError, ValueError):
            raise PluginCapabilityDenied(FILE_LIST_DENIED_REASON) from None
        return snapshot

    @staticmethod
    def _scan_file_list_entries(entries: Iterable[os.DirEntry[str]]) -> list[dict[str, str]]:
        snapshot: list[dict[str, str]] = []
        for entry in entries:
            if len(snapshot) >= MAX_FILE_LIST_ENTRIES:
                raise PluginCapabilityDenied(FILE_LIST_DENIED_REASON)
            snapshot.append(
                {"name": entry.name, "type": _file_list_entry_type(entry)}
            )
        snapshot.sort(key=lambda item: item["name"])
        return snapshot

    @classmethod
    def _scan_file_list_path(cls, resolved: Path) -> list[dict[str, str]]:
        with os.scandir(resolved) as entries:
            return cls._scan_file_list_entries(entries)

    @classmethod
    def _scan_file_list_no_follow(
        cls,
        file_root: Path,
        path_parts: tuple[str, ...],
        expected_identity: tuple[int, int, int],
    ) -> list[dict[str, str]]:
        flags = (
            os.O_RDONLY
            | os.O_DIRECTORY
            | os.O_NOFOLLOW
            | getattr(os, "O_CLOEXEC", 0)
        )
        descriptors: list[int] = []
        try:
            current_fd = os.open(file_root, flags)
            descriptors.append(current_fd)
            for part in path_parts:
                if part == ".":
                    continue
                current_fd = os.open(part, flags, dir_fd=current_fd)
                descriptors.append(current_fd)
            before = _directory_identity(os.fstat(current_fd))
            if before != expected_identity:
                raise PluginCapabilityDenied(FILE_LIST_DENIED_REASON)
            with os.scandir(current_fd) as entries:
                snapshot = cls._scan_file_list_entries(entries)
            after = _directory_identity(os.fstat(current_fd))
            if before != after:
                raise PluginCapabilityDenied(FILE_LIST_DENIED_REASON)
            return snapshot
        finally:
            for descriptor in reversed(descriptors):
                try:
                    os.close(descriptor)
                except OSError:
                    pass

    def _config_get_handler(
        self, config_root: Path, arguments: Mapping[str, Any]
    ) -> Any:
        """Return one whitelisted key from the plugin-bound config.json or default."""
        if not isinstance(arguments, Mapping) or set(arguments) - {"key", "default"}:
            raise PluginWorkerProtocolError(
                "config.get arguments must contain only key and default"
            )
        key = arguments.get("key")
        if not isinstance(key, str) or not _PLUGIN_CONFIG_KEY.fullmatch(key):
            raise PluginCapabilityDenied(CONFIG_GET_DENIED_REASON)
        config_path = config_root / PLUGIN_CONFIG_FILE
        try:
            config_details = config_path.lstat()
        except FileNotFoundError:
            return arguments.get("default")
        except OSError:
            raise PluginCapabilityDenied(CONFIG_GET_DENIED_REASON) from None
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        if bool(
            stat.S_ISLNK(config_details.st_mode)
            or getattr(config_details, "st_file_attributes", 0) & reparse_flag
        ):
            raise PluginCapabilityDenied(CONFIG_GET_DENIED_REASON)
        try:
            size = config_details.st_size
            if size > MAX_PLUGIN_CONFIG_BYTES:
                raise PluginCapabilityDenied(CONFIG_GET_DENIED_REASON)
            with config_path.open("rb") as handle:
                raw = handle.read(MAX_PLUGIN_CONFIG_BYTES + 1)
        except OSError:
            raise PluginCapabilityDenied(CONFIG_GET_DENIED_REASON) from None
        if len(raw) > MAX_PLUGIN_CONFIG_BYTES:
            raise PluginCapabilityDenied(CONFIG_GET_DENIED_REASON)
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            raise PluginCapabilityDenied(CONFIG_GET_DENIED_REASON) from None
        try:
            parsed = json.loads(text)
        except ValueError:
            raise PluginCapabilityDenied(CONFIG_GET_DENIED_REASON) from None
        if not isinstance(parsed, dict):
            raise PluginCapabilityDenied(CONFIG_GET_DENIED_REASON)
        if key not in parsed:
            return arguments.get("default")
        return parsed[key]

    def _llm_call_handler(self, arguments: Mapping[str, Any]) -> Any:
        """Return one parent-provided model reply for a bounded prompt."""
        if not isinstance(arguments, Mapping) or set(arguments) != {
            "prompt",
            "model",
        }:
            raise PluginWorkerProtocolError(
                "llm.call arguments must contain exactly prompt and model"
            )
        prompt = arguments["prompt"]
        model = arguments["model"]
        if not isinstance(prompt, str) or not prompt:
            raise PluginCapabilityDenied(LLM_CALL_DENIED_REASON)
        try:
            prompt_bytes = prompt.encode("utf-8")
        except UnicodeEncodeError:
            raise PluginCapabilityDenied(LLM_CALL_DENIED_REASON) from None
        if len(prompt_bytes) > MAX_LLM_PROMPT_BYTES:
            raise PluginCapabilityDenied(LLM_CALL_DENIED_REASON)
        if not isinstance(model, str) or not _LLM_MODEL.fullmatch(model):
            raise PluginCapabilityDenied(LLM_CALL_DENIED_REASON)
        with self._lock:
            provider = self._llm_provider
            if provider is None:
                raise PluginCapabilityDenied(LLM_CALL_DENIED_REASON)
        try:
            return provider(prompt, model)
        except PluginCapabilityDenied:
            raise
        except OSError:
            # TimeoutError and ConnectionError are OSError subclasses; both
            # mean the upstream provider was unavailable, not a client error.
            raise PluginCapabilityDenied(LLM_CALL_DENIED_REASON) from None

    def _network_get_handler(self, arguments: Mapping[str, Any]) -> Any:
        """Return one parent-owned bounded HTTP GET for an allowlisted host."""
        if not isinstance(arguments, Mapping) or set(arguments) != {"url"}:
            raise PluginWorkerProtocolError(
                "network.get arguments must contain exactly url"
            )
        raw_url = arguments["url"]
        if not isinstance(raw_url, str) or not raw_url:
            raise PluginCapabilityDenied(NETWORK_GET_DENIED_REASON)
        _validate_network_url(raw_url)
        with self._lock:
            allowlist = self._network_get_hosts
        if not allowlist:
            raise PluginCapabilityDenied(NETWORK_GET_DENIED_REASON)
        try:
            import requests
        except ImportError:
            raise PluginCapabilityDenied(NETWORK_GET_DENIED_REASON) from None
        current_url = raw_url
        session = requests.Session()
        session.trust_env = False
        try:
            for _ in range(MAX_NETWORK_REDIRECTS + 1):
                _scheme, host = _validate_network_url(current_url)
                if host not in allowlist:
                    raise PluginCapabilityDenied(NETWORK_GET_DENIED_REASON)
                try:
                    response = session.get(
                        current_url,
                        timeout=NETWORK_TIMEOUT_SECONDS,
                        allow_redirects=False,
                        stream=True,
                    )
                except requests.RequestException:
                    raise PluginCapabilityDenied(
                        NETWORK_GET_DENIED_REASON
                    ) from None
                with response:
                    status = response.status_code
                    if status in {301, 302, 303, 307, 308}:
                        location = response.headers.get("Location")
                        if not isinstance(location, str) or not location:
                            raise PluginCapabilityDenied(
                                NETWORK_GET_DENIED_REASON
                            )
                        try:
                            current_url = urljoin(current_url, location)
                        except ValueError:
                            raise PluginCapabilityDenied(
                                NETWORK_GET_DENIED_REASON
                            ) from None
                        continue
                    return _network_get_response(response, requests)
        except PluginCapabilityDenied:
            raise
        except requests.RequestException:
            raise PluginCapabilityDenied(NETWORK_GET_DENIED_REASON) from None
        except OSError:
            # TimeoutError and ConnectionError are OSError subclasses; both
            # mean the upstream host was unavailable, not a client error.
            raise PluginCapabilityDenied(NETWORK_GET_DENIED_REASON) from None
        finally:
            session.close()
        raise PluginCapabilityDenied(NETWORK_GET_DENIED_REASON)

    @staticmethod
    def _validate_event_arguments(arguments: Mapping[str, Any]) -> None:
        if not isinstance(arguments, Mapping):
            raise PluginWorkerProtocolError("event arguments must be an object")
        event_type = arguments.get("event_type")
        payload = arguments.get("payload")
        if not isinstance(event_type, str) or not _PLUGIN_EVENT_TYPE.fullmatch(event_type):
            raise PluginWorkerProtocolError("event type is invalid")
        try:
            payload_size = len(stable_json_bytes(payload))
        except PluginWorkerProtocolError:
            raise
        if payload_size > MAX_PLUGIN_EVENT_PAYLOAD_BYTES:
            raise OverflowError("event payload exceeds the V1 limit")


class PluginBrokerSession:
    """One lifecycle-bound, budgeted plugin broker request channel."""

    def __init__(
        self,
        broker: PluginBroker,
        plugin_id: str,
        request_id: str,
        declared_permissions: frozenset[str],
        generation: int,
        deadline: float | None,
    ) -> None:
        self._broker = broker
        self._plugin_id = plugin_id
        self._request_id = request_id
        self._declared_permissions = declared_permissions
        self._generation = generation
        self._deadline = deadline
        self._call_ids: set[str] = set()
        self._call_count = 0
        self._exchange_bytes = 0
        self._events: list[Event] = []
        self._aborted = False
        self._committed = False
        self._lock = threading.Lock()

    def handle(self, request: PluginBrokerRequest) -> PluginBrokerResult:
        """Validate one request and stage only an authorized V1 event."""
        if not isinstance(request, PluginBrokerRequest):
            raise ValueError("request must be a PluginBrokerRequest")
        try:
            argument_bytes = len(stable_json_bytes(request.arguments))
            exchange_bytes = len(stable_json_bytes(request.to_dict()))
        except PluginWorkerProtocolError:
            return self._deny(request, "invalid_arguments", 0)

        with self._lock:
            if request.request_id != self._request_id:
                return self._deny(request, "request_mismatch", argument_bytes)
            if request.plugin_id != self._plugin_id:
                return self._deny(request, "plugin_mismatch", argument_bytes)
            if not self._broker._is_active_generation(
                self._plugin_id, self._generation
            ):
                return self._deny(request, "generation_mismatch", argument_bytes)
            if request.call_id in self._call_ids:
                return self._deny(request, "duplicate_call_id", argument_bytes)
            if self._call_count >= MAX_BROKER_CALLS:
                return self._deny(request, "call_budget_exceeded", argument_bytes)
            self._call_ids.add(request.call_id)
            self._call_count += 1
            if self._exchange_bytes + exchange_bytes > MAX_BROKER_EXCHANGE_BYTES:
                return self._deny(request, "exchange_budget_exceeded", argument_bytes)
            self._exchange_bytes += exchange_bytes

        if not isinstance(request.arguments, Mapping):
            return self._deny(request, "invalid_arguments", argument_bytes)
        required_permission = MANIFEST_PERMISSION_BY_CAPABILITY.get(request.capability)
        if required_permission is None:
            return self._deny(request, "capability_not_supported", argument_bytes)
        if required_permission not in self._declared_permissions:
            return self._deny(request, "capability_not_declared", argument_bytes)
        if request.capability not in self._broker._grants.get(
            self._plugin_id, frozenset()
        ):
            return self._deny(request, "capability_not_granted", argument_bytes)
        rooted = _ROOTED_CAPABILITY_HANDLERS.get(request.capability)
        if rooted is not None:
            registered_flag, handler_name, denied_reason = rooted
            if not getattr(self._broker, registered_flag):
                return self._deny(request, "capability_not_registered", argument_bytes)
            plugin_root = self._broker._file_root_for(self._plugin_id)
            if plugin_root is None:
                return self._deny(request, denied_reason, argument_bytes)
            handler = functools.partial(
                getattr(self._broker, handler_name), plugin_root
            )
        else:
            handler = self._broker._handler_for(request.capability)
            if handler is None:
                return self._deny(request, "capability_not_registered", argument_bytes)

        try:
            result = handler(request.arguments)
        except PluginCapabilityDenied as error:
            return self._deny(request, error.reason, argument_bytes)
        except OverflowError:
            return self._deny(request, "payload_too_large", argument_bytes)
        except PluginWorkerProtocolError:
            return self._deny(request, "invalid_arguments", argument_bytes)
        except Exception:
            return self._deny(request, "handler_failed", argument_bytes)
        try:
            result_size = bounded_stable_json_size(
                result, MAX_BROKER_EXCHANGE_BYTES
            )
        except OverflowError:
            return self._deny(request, "result_too_large", argument_bytes)
        except PluginWorkerProtocolError:
            return self._deny(request, "handler_result_invalid", argument_bytes)
        with self._lock:
            if self._aborted or self._committed:
                return self._deny(request, "session_closed", argument_bytes)
            result_exceeds_budget = (
                self._exchange_bytes + result_size > MAX_BROKER_EXCHANGE_BYTES
            )
            if not result_exceeds_budget:
                self._exchange_bytes += result_size
                if request.capability == EVENT_EMIT_CAPABILITY:
                    self._events.append(
                        Event(
                            event_type=request.arguments["event_type"],
                            source=f"plugin:{self._plugin_id}",
                            data=request.arguments["payload"],
                        )
                    )
        if result_exceeds_budget:
            return self._deny(request, "result_too_large", argument_bytes)
        self._broker._record(request, True, "allowed", argument_bytes)
        return PluginBrokerResult(
            request_id=request.request_id,
            call_id=request.call_id,
            plugin_id=request.plugin_id,
            allowed=True,
            result=result,
            error="",
        )

    def commit_events(self) -> bool:
        """Commit this lifecycle's complete outbox without blocking on subscribers."""
        with self._lock:
            if self._aborted or self._committed:
                return False
            if not self._broker._event_bus.record_many(
                self._events, deadline=self._deadline
            ):
                return False
            self._events.clear()
            self._committed = True
            return True

    def abort(self) -> None:
        """Permanently discard this lifecycle's uncommitted outbox."""
        with self._lock:
            self._events.clear()
            self._aborted = True

    def _deny(
        self,
        request: PluginBrokerRequest,
        error: str,
        argument_bytes: int,
    ) -> PluginBrokerResult:
        self._broker._record(request, False, error, argument_bytes)
        return PluginBrokerResult(
            request_id=request.request_id,
            call_id=request.call_id,
            plugin_id=request.plugin_id,
            allowed=False,
            result=None,
            error=error,
        )
