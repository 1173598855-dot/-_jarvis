"""
上下文压缩器 - 小奕 J.A.R.V.I.S. 记忆维护核心
萃取自 Mem0 的记忆向量化逻辑 + Claude Code 的 consolidate-memory 技能

功能：
1. 上下文无损压缩：长对话自动摘要，保留关键信息
2. 记忆持久化：将关键决策写入 .auto-memory/ 目录
3. 记忆索引维护：更新 MEMORY.md 索引
4. 重复检测：识别并合并重复记忆
5. 过期清理：归档过时信息
6. 语义压缩：基于重要性评分的智能压缩（继承自 semantic_compressor）
7. Token 预算管理：限制上下文窗口使用
8. 分层记忆：四种记忆类型

运行：python context_compressor.py [compress|store|consolidate|stats|list]
"""

import hashlib
import hmac
import json
import math
import os
import re
import stat
import sys
import threading
import weakref
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from itertools import islice
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.contracts.bounded_json import read_bounded_json
from core.contracts.durable_directory import fsync_directory

LLM_COMPRESSION_HISTORY_LIMIT = 1000
_MEMORY_INDEX_MAX_BYTES = 8 * 1024 * 1024
_MEMORY_ENTRY_MAX_BYTES = 8 * 1024 * 1024
_MEMORY_LEGACY_DIRECTORY_ENTRIES = 8_192
_MEMORY_ENTRY_SCHEMA_VERSION = 2
_MEMORY_ENTRY_ID_MAX_CHARS = 128
_MEMORY_MERGE_CONTENT_MAX_CHARS = 8192
_MEMORY_TITLE_MARKERS = (" [truncated]", " [summary]", " [llm-summary]")
_MEMORY_TRUNCATION_MARKER = (
    "\n... [truncated, see original record for full content] ...\n"
)
_MEMORY_MERGE_SOURCE_IDS_MAX = 64
_MEMORY_MERGE_SEPARATOR = "\n\n--- merged duplicate ---\n\n"
_MEMORY_JOURNAL_NAME = ".memory-journal"
_MEMORY_JOURNAL_MAX_BYTES = 4096
_MEMORY_JOURNAL_SCHEMA_VERSION = 1
_MEMORY_JOURNAL_OPERATIONS = frozenset({"store", "delete"})
_MEMORY_JOURNAL_FIELDS = frozenset({"schema_version", "operation", "filename"})
_MEMORY_TEMPORARY_SUFFIX = ".tmp"
_MEMORY_TEMPORARY_TOKEN_CHARS = 32
_MEMORY_ENTRY_ID_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
)
_MEMORY_ENTRY_V2_REQUIRED_FIELDS = frozenset({
    "schema_version",
    "id",
    "name",
    "type",
    "metadata_json",
    "tags_json",
    "created_at",
    "last_accessed",
    "access_count",
    "importance",
    "token_count",
    "compressed",
    "parent_id",
    "probe_cleanup_token",
})
_MEMORY_ENTRY_V2_OPTIONAL_FIELDS = frozenset({"description"})
_MEMORY_STORE_LOCKS_GUARD = threading.Lock()
_MEMORY_STORE_LOCKS = weakref.WeakValueDictionary()


def _base_title(title: str) -> str:
    """Strip repeated compression markers from a title.

    Compression appends a marker to the title, so a transformed record used to
    stop colliding with its untransformed twin and duplicate detection silently
    stopped working across consolidation rounds.
    """
    if type(title) is not str:
        return title
    stripped = title
    changed = True
    while changed:
        changed = False
        for marker in _MEMORY_TITLE_MARKERS:
            if stripped.endswith(marker):
                stripped = stripped[: -len(marker)]
                changed = True
    return stripped


def _marked_title(title: str, marker: str) -> str:
    """Append one compression marker without stacking it on repeated passes."""
    base = _base_title(title)
    return base + marker


class _MemoryPayloadTooLarge(ValueError):
    """Internal sentinel for the bounded MemoryStore serializer."""


class _BoundedUtf8Builder:
    """Build a UTF-8 payload while stopping at a fixed byte budget."""

    __slots__ = ("_limit", "_parts", "_size")

    _CHUNK_CHARS = 64 * 1024

    def __init__(self, limit: int):
        self._limit = limit
        self._parts: List[bytes] = []
        self._size = 0

    def append_text(self, value: str) -> None:
        for offset in range(0, len(value), self._CHUNK_CHARS):
            self.append_bytes(value[offset:offset + self._CHUNK_CHARS].encode("utf-8"))

    def append_json(self, value: Any, encoder: json.JSONEncoder) -> None:
        for chunk in encoder.iterencode(value):
            self.append_text(chunk)

    def append_bytes(self, value: bytes) -> None:
        next_size = self._size + len(value)
        if next_size > self._limit:
            raise _MemoryPayloadTooLarge("memory entry exceeds the size limit")
        self._parts.append(value)
        self._size = next_size

    def finish(self) -> bytes:
        return b"".join(self._parts)


def _reject_duplicate_json_keys(items):
    value = {}
    for key, item in items:
        if key in value:
            raise ValueError("duplicate JSON object key")
        value[key] = item
    return value


def _reject_json_constant(value):
    raise ValueError(f"non-finite JSON constant is not allowed: {value}")


def _memory_store_lock(memory_dir: Path) -> threading.RLock:
    key = str(memory_dir.resolve())
    with _MEMORY_STORE_LOCKS_GUARD:
        lock = _MEMORY_STORE_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _MEMORY_STORE_LOCKS[key] = lock
        return lock


def _memory_store_mutex_name(memory_dir: Path) -> str:
    canonical = os.path.normcase(
        os.path.normpath(str(memory_dir.resolve(strict=False)))
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return rf"Global\JARVIS.MemoryStore.v1.{digest}"


@contextmanager
def _windows_memory_store_mutex(memory_dir: Path):
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_mutex = kernel32.CreateMutexW
    create_mutex.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    create_mutex.restype = wintypes.HANDLE
    wait_for_single_object = kernel32.WaitForSingleObject
    wait_for_single_object.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    wait_for_single_object.restype = wintypes.DWORD
    release_mutex = kernel32.ReleaseMutex
    release_mutex.argtypes = [wintypes.HANDLE]
    release_mutex.restype = wintypes.BOOL
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL

    handle = create_mutex(None, False, _memory_store_mutex_name(memory_dir))
    if not handle:
        raise OSError("cannot create the memory store mutex") from ctypes.WinError(
            ctypes.get_last_error()
        )

    acquired = False
    try:
        wait_result = wait_for_single_object(handle, 0xFFFFFFFF)
        if wait_result not in (0x00000000, 0x00000080):
            if wait_result == 0xFFFFFFFF:
                cause = ctypes.WinError(ctypes.get_last_error())
            else:
                cause = OSError(f"unexpected mutex wait result: {wait_result}")
            raise OSError("cannot acquire the memory store mutex") from cause
        acquired = True
        yield
    finally:
        release_error = None
        if acquired and not release_mutex(handle):
            release_error = ctypes.WinError(ctypes.get_last_error())
        close_error = None
        if not close_handle(handle):
            close_error = ctypes.WinError(ctypes.get_last_error())
        if release_error is not None:
            raise OSError("cannot release the memory store mutex") from release_error
        if close_error is not None:
            raise OSError("cannot close the memory store mutex") from close_error


@contextmanager
def _memory_store_process_lock(memory_dir: Path):
    if os.name == "nt":
        with _windows_memory_store_mutex(memory_dir):
            yield
        return

    import fcntl

    lock_flags = (
        os.O_RDWR
        | os.O_CREAT
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    lock_descriptor = os.open(memory_dir / ".memory-store.lock", lock_flags, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(lock_descriptor).st_mode):
            raise OSError("memory store lock must be a regular file")
        fcntl.flock(lock_descriptor, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
    finally:
        os.close(lock_descriptor)


class MemoryType(Enum):
    USER = "user"
    FEEDBACK = "feedback"
    PROJECT = "project"
    REFERENCE = "reference"


_MEMORY_TYPE_VALUES = frozenset(member.value for member in MemoryType)


class CompressionStrategy(Enum):
    """压缩策略"""
    NONE = "none"
    TRUNCATE = "truncate"
    SUMMARIZE = "summarize"
    SEMANTIC = "semantic"


@dataclass
class MemoryEntry:
    id: str
    type: MemoryType
    title: str
    content: str
    metadata: Dict[str, Any]
    created_at: str
    last_accessed: str
    access_count: int
    tags: List[str]
    importance: float = 0.0
    token_count: int = 0
    compressed: bool = False
    parent_id: Optional[str] = None

    @classmethod
    def create(cls, memory_type: MemoryType, title: str, content: str,
               metadata: Optional[Dict[str, Any]] = None,
               tags: Optional[List[str]] = None,
               importance: float = 0.5) -> "MemoryEntry":
        entry_id = hashlib.md5(f"{title}:{content[:50]}".encode()).hexdigest()[:12]
        now = datetime.now().isoformat()
        return cls(
            id=entry_id, type=memory_type, title=title, content=content,
            metadata=metadata or {}, created_at=now, last_accessed=now,
            access_count=0, tags=tags or [], importance=importance,
            token_count=cls._estimate_tokens(content),
        )

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """
        估算文本的 Token 数量

        启发式规则：
        - 英文：约 4 字符/token
        - 中文：约 1.5 字符/token
        - 代码：约 3 字符/token
        """
        if not text:
            return 0

        chinese_chars = len(re.findall(r'[一-鿿]', text))
        english_chars = len(re.findall(r'[a-zA-Z]', text))
        code_chars = len(re.findall(r'[{}()\[\];<>/\\|]', text))

        total = (
            chinese_chars / 1.5
            + english_chars / 4.0
            + code_chars / 3.0
            + len(text) * 0.1
        )

        return max(1, int(total))


class ContextCompressor:
    """上下文无损压缩器 - 长对话自动摘要"""

    def __init__(self, max_tokens: int = 4000):
        self.max_tokens = max_tokens

    def compress(self, conversation: List[Dict[str, str]]) -> str:
        if len(conversation) <= 5:
            return self._format_conversation(conversation)
        recent = conversation[-5:]
        older = conversation[:-5]
        summary = self._summarize(older)
        return f"[摘要] {summary}\n\n[最近对话]\n{self._format_conversation(recent)}"

    def _summarize(self, messages: List[Dict[str, str]]) -> str:
        decisions, facts = [], []
        for msg in messages:
            content = msg.get("content", "")
            role = msg.get("role", "")
            if any(kw in content for kw in ["决定", "选择", "方案", "确定", "decided", "chosen"]):
                decisions.append(f"{role}: {content[:100]}")
            if any(kw in content for kw in ["版本", "路径", "配置", "version", "path", "config"]):
                facts.append(f"{role}: {content[:100]}")
        parts = []
        if decisions:
            parts.append(f"决策 ({len(decisions)}): " + "; ".join(decisions[:3]))
        if facts:
            parts.append(f"关键事实 ({len(facts)}): " + "; ".join(facts[:3]))
        return " | ".join(parts) if parts else f"{len(messages)} 条消息已压缩"

    def _format_conversation(self, messages: List[Dict[str, str]]) -> str:
        return "\n".join([f"{m.get('role', '?')}: {m.get('content', '')[:200]}" for m in messages])


class SemanticCompressor:
    """语义压缩器 - 基于内容重要性的智能压缩（继承自 semantic_compressor）"""

    def __init__(self, token_budget: int = 4000):
        self.token_budget = token_budget

    def compress(self, entries: List[MemoryEntry]) -> Tuple[List[MemoryEntry], Dict[str, int]]:
        stats = {
            "total": len(entries),
            "kept": 0,
            "summarized": 0,
            "pruned": 0,
            "merged": 0,
            "tokens_saved": 0,
        }

        sorted_entries = sorted(entries, key=lambda e: e.importance, reverse=True)

        kept = []
        current_tokens = 0

        for entry in sorted_entries:
            if self._is_expired(entry) and entry.importance < 0.5:
                stats["pruned"] += 1
                stats["tokens_saved"] += entry.token_count
                continue

            if current_tokens + entry.token_count > self.token_budget:
                if entry.importance >= 0.7:
                    truncated = self._truncate(entry)
                    kept.append(truncated)
                    stats["kept"] += 1
                    stats["tokens_saved"] += entry.token_count - truncated.token_count
                    current_tokens += truncated.token_count
                elif entry.importance >= 0.3:
                    summarized = self._summarize(entry)
                    kept.append(summarized)
                    stats["summarized"] += 1
                    stats["tokens_saved"] += entry.token_count - summarized.token_count
                    current_tokens += summarized.token_count
                else:
                    stats["pruned"] += 1
                    stats["tokens_saved"] += entry.token_count
            else:
                kept.append(entry)
                stats["kept"] += 1
                current_tokens += entry.token_count

        merged = self._merge_duplicates(kept)
        stats["merged"] = len(kept) - len(merged)
        stats["remaining"] = len(merged)

        return merged, stats

    def _is_expired(self, entry: MemoryEntry) -> bool:
        if entry.access_count >= 5:
            return False
        try:
            last_accessed = datetime.fromisoformat(entry.last_accessed)
            cutoff = datetime.now() - timedelta(days=30)
            return last_accessed < cutoff
        except (ValueError, TypeError):
            return False

    def _truncate(self, entry: MemoryEntry, max_tokens: int = 500) -> MemoryEntry:
        if entry.token_count <= max_tokens:
            return entry
        truncated_content = self._truncated_body(entry.content, max_tokens)
        return MemoryEntry(
            id=entry.id, type=entry.type,
            title=_marked_title(entry.title, " [truncated]"),
            content=truncated_content, metadata={**entry.metadata, "truncated": True},
            created_at=entry.created_at, last_accessed=entry.last_accessed,
            access_count=entry.access_count, tags=entry.tags,
            importance=entry.importance,
            token_count=MemoryEntry._estimate_tokens(truncated_content),
            compressed=True, parent_id=entry.id,
        )

    @staticmethod
    def _truncated_body(content: str, max_tokens: int) -> str:
        """Keep the largest head/tail pair whose estimate fits `max_tokens`.

        The previous implementation kept the leading 60% and the trailing 40%,
        which is the whole body plus a marker, so "truncation" grew the record
        and raised its token count on every pass. The token estimate rises
        monotonically with kept length for a fixed body, so the largest fitting
        length is found by bisection over the number of kept characters.
        """
        marker = _MEMORY_TRUNCATION_MARKER
        if MemoryEntry._estimate_tokens(marker) >= max_tokens:
            return marker

        def build(kept: int) -> str:
            head = (kept * 6) // 10
            tail = kept - head
            return content[:head] + marker + (content[-tail:] if tail else "")

        low, high = 0, len(content)
        while low < high:
            middle = (low + high + 1) // 2
            if MemoryEntry._estimate_tokens(build(middle)) <= max_tokens:
                low = middle
            else:
                high = middle - 1

        # The estimate is non-decreasing in kept length for a fixed body, so the
        # bisection result already fits. Halving until it does keeps the budget
        # authoritative even if the estimator is retuned later.
        while low and MemoryEntry._estimate_tokens(build(low)) > max_tokens:
            low //= 2
        return build(low)

    def _summarize(self, entry: MemoryEntry) -> MemoryEntry:
        content = entry.content
        sentences = re.split(r'[。.!?\n]', content)
        sentences = [s.strip() for s in sentences if s.strip()]

        keywords = ["决定", "选择", "方案", "确定", "decided", "chosen", "must", "should", "constraint"]
        key_sentences = [s for s in sentences if any(kw in s.lower() for kw in keywords)]

        if key_sentences:
            summary = "; ".join(key_sentences[:3])
        else:
            summary = "; ".join(sentences[:3])

        summary = f"[summary] {summary}" if summary else "[summary] content compressed"

        return MemoryEntry(
            id=entry.id, type=entry.type,
            title=_marked_title(entry.title, " [summary]"),
            content=summary, metadata={**entry.metadata, "summarized": True, "original_length": len(content)},
            created_at=entry.created_at, last_accessed=entry.last_accessed,
            access_count=entry.access_count, tags=entry.tags,
            importance=entry.importance * 0.9,
            token_count=MemoryEntry._estimate_tokens(summary),
            compressed=True, parent_id=entry.id,
        )

    def _merge_duplicates(self, entries: List[MemoryEntry]) -> List[MemoryEntry]:
        """Fold same-title records into one survivor without dropping content.

        Selecting the higher-access record and discarding the other used to be
        invisible, because the dropped file stayed on disk. Consolidation now
        deletes non-surviving files, so the survivor has to absorb the other
        record's distinct content. When absorbing would exceed the merge
        content budget both records are kept instead, so a bounded merge never
        turns into silent data loss.
        """
        merged: List[MemoryEntry] = []
        positions: Dict[str, int] = {}
        for entry in entries:
            key = _base_title(entry.title)
            position = positions.get(key)
            if position is None:
                positions[key] = len(merged)
                merged.append(entry)
                continue
            absorbed = self._absorb_duplicate(merged[position], entry)
            if absorbed is None:
                merged.append(entry)
                continue
            merged[position] = absorbed
        return merged

    @classmethod
    def _absorb_duplicate(
        cls,
        survivor: MemoryEntry,
        duplicate: MemoryEntry,
    ) -> Optional[MemoryEntry]:
        """Return one record carrying both bodies, or None when it will not fit.

        The higher-access record keeps its identity, so the surviving filename
        and the previous selection rule are unchanged. Content already present
        in the survivor is not appended, which keeps repeated consolidation
        idempotent.
        """
        primary, secondary = survivor, duplicate
        if duplicate.access_count > survivor.access_count:
            primary, secondary = duplicate, survivor

        content = primary.content
        absorbed_content = bool(secondary.content) and secondary.content not in content
        if absorbed_content:
            content = content + _MEMORY_MERGE_SEPARATOR + secondary.content
            if len(content) > _MEMORY_MERGE_CONTENT_MAX_CHARS:
                return None

        tags = list(primary.tags)
        for tag in secondary.tags:
            if tag not in tags:
                tags.append(tag)

        sources = cls._merged_source_ids(primary)
        for candidate in (*cls._merged_source_ids(secondary), secondary.id):
            if type(candidate) is str and candidate not in sources:
                sources.append(candidate)
        metadata = dict(primary.metadata)
        metadata["merged_from"] = sources[:_MEMORY_MERGE_SOURCE_IDS_MAX]

        # A merged body is no longer purely one record's summary or truncation,
        # so a survivor that absorbed a differently marked twin drops back to the
        # shared base title.
        title = (
            primary.title
            if primary.title == secondary.title
            else _base_title(primary.title)
        )

        return MemoryEntry(
            id=primary.id,
            type=primary.type,
            title=title,
            content=content,
            metadata=metadata,
            created_at=min(primary.created_at, secondary.created_at),
            last_accessed=max(primary.last_accessed, secondary.last_accessed),
            access_count=max(primary.access_count, secondary.access_count),
            tags=tags,
            importance=max(primary.importance, secondary.importance),
            token_count=MemoryEntry._estimate_tokens(content),
            compressed=(
                primary.compressed and secondary.compressed
                if absorbed_content
                else primary.compressed
            ),
            parent_id=primary.parent_id,
        )

    @staticmethod
    def _merged_source_ids(entry: MemoryEntry) -> List[str]:
        """Read the recorded absorbed ids, tolerating externally written files."""
        metadata = entry.metadata
        if type(metadata) is not dict:
            return []
        recorded = metadata.get("merged_from")
        if type(recorded) is not list:
            return []
        return [item for item in recorded if type(item) is str][
            :_MEMORY_MERGE_SOURCE_IDS_MAX
        ]


class MemoryStore:
    """记忆持久化存储 - 管理 .auto-memory/ 目录"""

    def __init__(
        self,
        memory_dir: str = ".auto-memory",
        token_budget: int = 4000,
        *,
        read_only: bool = False,
    ):
        self.read_only = bool(read_only)
        self.memory_dir = Path(memory_dir)
        self._mutation_lock = _memory_store_lock(self.memory_dir)
        if self.read_only:
            self.memory_dir = self.memory_dir.resolve()
        else:
            self._ensure_writable_root()
        self.index_file = self.memory_dir / "MEMORY.md"
        self.journal_file = self.memory_dir / _MEMORY_JOURNAL_NAME
        self.token_budget = token_budget
        self.compressor = SemanticCompressor(token_budget=token_budget)
        self._recovering_journal = False
        self._purged_stray_temporaries = False
        if not self.read_only:
            self._ensure_index()

    def _ensure_writable_root(self) -> None:
        """Create or validate the configured root without following links."""
        try:
            root_stat = os.lstat(self.memory_dir)
        except FileNotFoundError:
            try:
                self.memory_dir.mkdir()
            except FileExistsError:
                pass
            try:
                root_stat = os.lstat(self.memory_dir)
            except OSError as error:
                raise OSError("memory root cannot be validated") from error
        except OSError as error:
            raise OSError("memory root cannot be validated") from error
        if (
            not stat.S_ISDIR(root_stat.st_mode)
            or self._is_reparse_point(root_stat)
        ):
            raise OSError("memory root must be a directory")

    def _require_writable(self) -> None:
        if self.read_only:
            raise PermissionError("MemoryStore is read-only")

    @contextmanager
    def _mutation_transaction(self):
        self._require_writable()
        with self._mutation_lock:
            with _memory_store_process_lock(self.memory_dir):
                if not self._recovering_journal:
                    self._recovering_journal = True
                    try:
                        self._recover_journal_unlocked()
                    finally:
                        self._recovering_journal = False
                yield

    def _recover_journal_unlocked(self) -> None:
        """Roll one interrupted entry/index publication forward, then clear it.

        `MEMORY.md` is derived state and the entry file is authoritative. The
        journal only records which filename a mutation was about to publish, so
        reconciliation restores one invariant: the index holds a row for that
        filename exactly when the entry file exists and parses. Applying the
        same journal twice is therefore a no-op.
        """
        record = self._read_journal_unlocked()
        if record is None:
            self._purge_stray_temporaries_unlocked(once_per_instance=True)
            return

        filename = record["filename"]
        filepath = self.memory_dir / filename
        self._ensure_index_unlocked()
        expected_index_stat = self._ensure_regular_index_target()
        index_content = self._read_index_unlocked()

        try:
            entry_stat = os.lstat(filepath)
        except FileNotFoundError:
            payload = self._render_index_removal(index_content, filename)
        except OSError as error:
            raise OSError("journalled memory entry cannot be inspected") from error
        else:
            if (
                not stat.S_ISREG(entry_stat.st_mode)
                or self._is_reparse_point(entry_stat)
            ):
                raise OSError("journalled memory entry must be a regular file")
            content = self._read_regular_candidate(filepath, normalize_newlines=False)
            if content is None:
                raise OSError("journalled memory entry cannot be read")
            try:
                entry = self._parse_entry(filepath, content)
            except (
                OSError,
                UnicodeError,
                TypeError,
                ValueError,
                OverflowError,
                RecursionError,
            ):
                entry = None
            if entry is None:
                # No row can be derived from an unparseable entry, and this store
                # only ever publishes round-tripped v2 payloads. The surviving
                # file therefore came from legacy content or an external writer,
                # so the existing index is left exactly as it is.
                payload = index_content.encode("utf-8")
            else:
                payload = self._render_index_update(entry, filename, index_content)

        if payload != index_content.encode("utf-8"):
            self._atomic_write_regular_target(
                self.index_file,
                payload,
                expected_index_stat,
                label="memory index recovery",
            )
        self._purge_stray_temporaries_unlocked()
        self._clear_journal_unlocked()

    def _write_journal_unlocked(self, operation: str, filename: str) -> None:
        """Record one mutation intent durably before the entry file changes."""
        if operation not in _MEMORY_JOURNAL_OPERATIONS:
            raise OSError("memory journal operation is not supported")
        if not self._is_journalled_filename(filename):
            raise OSError("memory journal filename is not supported")
        try:
            os.lstat(self.journal_file)
        except FileNotFoundError:
            pass
        except OSError as error:
            raise OSError("memory journal cannot be inspected") from error
        else:
            raise OSError("memory journal was not cleared before this mutation")

        payload = json.dumps(
            {
                "schema_version": _MEMORY_JOURNAL_SCHEMA_VERSION,
                "operation": operation,
                "filename": filename,
            },
            ensure_ascii=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8") + b"\n"
        if len(payload) > _MEMORY_JOURNAL_MAX_BYTES:
            raise OSError("memory journal exceeds the size limit")
        self._atomic_write_regular_target(
            self.journal_file,
            payload,
            None,
            label="memory journal",
        )

    def _clear_journal_unlocked(self) -> None:
        """Remove a completed intent record and make the removal durable."""
        try:
            journal_stat = os.lstat(self.journal_file)
        except FileNotFoundError:
            return
        except OSError as error:
            raise OSError("memory journal cannot be inspected") from error
        if (
            not stat.S_ISREG(journal_stat.st_mode)
            or self._is_reparse_point(journal_stat)
        ):
            raise OSError("memory journal must be a regular file")
        try:
            self.journal_file.unlink()
        except FileNotFoundError:
            return
        except OSError as error:
            raise OSError("memory journal cannot be cleared") from error
        self._flush_parent_directory(self.journal_file, label="memory journal")

    def _read_journal_unlocked(self) -> Optional[Dict[str, Any]]:
        """Return one validated intent record, or None when no journal exists."""
        try:
            journal_stat = os.lstat(self.journal_file)
        except FileNotFoundError:
            return None
        except OSError as error:
            raise OSError("memory journal cannot be inspected") from error
        if (
            not stat.S_ISREG(journal_stat.st_mode)
            or self._is_reparse_point(journal_stat)
        ):
            raise OSError("memory journal must be a regular file")
        if journal_stat.st_size > _MEMORY_JOURNAL_MAX_BYTES:
            raise OSError("memory journal exceeds the size limit")
        content, _ = self._read_regular_file(
            self.journal_file,
            journal_stat,
            _MEMORY_JOURNAL_MAX_BYTES,
        )
        if content is None:
            raise OSError("memory journal cannot be read")
        try:
            record = json.loads(
                content,
                object_pairs_hook=_reject_duplicate_json_keys,
                parse_constant=_reject_json_constant,
            )
        except (TypeError, ValueError, RecursionError) as error:
            raise OSError("memory journal is not valid JSON") from error
        if type(record) is not dict or set(record) != _MEMORY_JOURNAL_FIELDS:
            raise OSError("memory journal record is malformed")
        if (
            type(record["schema_version"]) is not int
            or record["schema_version"] != _MEMORY_JOURNAL_SCHEMA_VERSION
        ):
            raise OSError("memory journal schema version is not supported")
        if (
            type(record["operation"]) is not str
            or record["operation"] not in _MEMORY_JOURNAL_OPERATIONS
        ):
            raise OSError("memory journal operation is not supported")
        if not self._is_journalled_filename(record["filename"]):
            raise OSError("memory journal filename is not supported")
        return record

    @classmethod
    def _is_journalled_filename(cls, value: Any) -> bool:
        """Accept only the exact `<type>_<id>.md` names this store publishes."""
        if type(value) is not str or not value.endswith(".md"):
            return False
        memory_type, separator, entry_id = value[: -len(".md")].partition("_")
        return (
            bool(separator)
            and memory_type in _MEMORY_TYPE_VALUES
            and cls._is_safe_entry_id(entry_id)
        )

    def _purge_stray_temporaries_unlocked(
        self,
        *,
        once_per_instance: bool = False,
    ) -> None:
        """Best-effort removal of temporaries a crashed atomic write left behind.

        Temporaries only exist inside `_atomic_write_regular_target()`, which
        runs under this store's process lock, so no cooperating instance can own
        one while this runs. Failures are ignored: a stray temporary never
        breaks the entry/index invariant.
        """
        if once_per_instance:
            if self._purged_stray_temporaries:
                return
            self._purged_stray_temporaries = True

        candidates = []
        try:
            with os.scandir(self.memory_dir) as scanner:
                for candidate in scanner:
                    if len(candidates) >= _MEMORY_LEGACY_DIRECTORY_ENTRIES:
                        return
                    candidates.append(candidate)
        except (OSError, TypeError, ValueError, OverflowError):
            return

        for candidate in candidates:
            if not self._is_stray_temporary_name(candidate.name):
                continue
            try:
                if candidate.is_symlink() or not candidate.is_file(
                    follow_symlinks=False
                ):
                    continue
                os.unlink(candidate.path)
            except OSError:
                continue

    @classmethod
    def _is_stray_temporary_name(cls, name: str) -> bool:
        """Match only the temporary names `_atomic_write_regular_target()` creates."""
        if not name.startswith(".") or not name.endswith(_MEMORY_TEMPORARY_SUFFIX):
            return False
        remainder = name[1 : -len(_MEMORY_TEMPORARY_SUFFIX)]
        base, separator, token = remainder.rpartition(".")
        if not separator or len(token) != _MEMORY_TEMPORARY_TOKEN_CHARS:
            return False
        if any(character not in "0123456789abcdef" for character in token):
            return False
        return (
            base == "MEMORY.md"
            or base == _MEMORY_JOURNAL_NAME
            or cls._is_journalled_filename(base)
        )

    def _ensure_index(self):
        with self._mutation_transaction():
            self._ensure_index_unlocked()

    def _ensure_index_unlocked(self):
        try:
            index_stat = os.lstat(self.index_file)
        except FileNotFoundError:
            with self.index_file.open("x", encoding="utf-8") as handle:
                handle.write("# Memory Index\n\n")
                handle.flush()
                os.fsync(handle.fileno())
            self._flush_parent_directory(self.index_file, label="memory index")
            return
        if (
            not stat.S_ISREG(index_stat.st_mode)
            or self._is_reparse_point(index_stat)
        ):
            raise OSError("memory index must be a regular file")

    def _ensure_regular_index_target(self) -> os.stat_result:
        self._ensure_index_unlocked()
        try:
            index_stat = os.lstat(self.index_file)
        except OSError as error:
            raise OSError("memory index must be a regular file") from error
        if (
            not stat.S_ISREG(index_stat.st_mode)
            or self._is_reparse_point(index_stat)
        ):
            raise OSError("memory index must be a regular file")
        return index_stat

    def store(self, entry: MemoryEntry) -> str:
        with self._mutation_transaction():
            return self._store_unlocked(entry)

    def _store_unlocked(self, entry: MemoryEntry) -> str:
        filename, payload = self._serialize_entry(entry)
        filepath = self.memory_dir / filename
        expected_entry_stat = self._ensure_regular_entry_target(filepath)
        previous_entry_payload = self._read_existing_entry_payload(
            filepath,
            expected_entry_stat,
        )
        expected_index_stat = self._ensure_regular_index_target()
        index_content = self._read_index_unlocked()
        index_payload = self._render_index_update(entry, filename, index_content)
        self._write_journal_unlocked("store", filename)
        installed_entry_stat = self._atomic_write_regular_target(
            filepath,
            payload,
            expected_entry_stat,
            label="memory entry",
        )
        try:
            self._atomic_write_regular_target(
                self.index_file,
                index_payload,
                expected_index_stat,
                label="memory index",
            )
        except OSError as index_error:
            try:
                self._restore_entry_after_index_failure(
                    filepath,
                    previous_entry_payload,
                    installed_entry_stat,
                )
            except OSError as rollback_error:
                rollback_error.add_note(f"index update also failed: {index_error}")
                raise OSError("memory entry rollback failed") from rollback_error
            raise
        self._clear_journal_unlocked()
        return str(filepath)

    @staticmethod
    def _is_safe_entry_id(value: Any) -> bool:
        return (
            type(value) is str
            and 0 < len(value) <= _MEMORY_ENTRY_ID_MAX_CHARS
            and all(character in _MEMORY_ENTRY_ID_CHARS for character in value)
        )

    @staticmethod
    def _validate_json_value(value: Any, field_name: str) -> None:
        stack = [(value, False)]
        active_containers = set()
        while stack:
            candidate, leaving = stack.pop()
            candidate_type = type(candidate)
            if leaving:
                active_containers.remove(id(candidate))
                continue
            if candidate is None or candidate_type in (str, bool, int):
                continue
            if candidate_type is float:
                if not math.isfinite(candidate):
                    raise ValueError(f"{field_name} must contain finite JSON numbers")
                continue
            if candidate_type not in (list, dict):
                raise TypeError(f"{field_name} must contain only JSON values")

            container_id = id(candidate)
            if container_id in active_containers:
                raise ValueError(f"{field_name} must not contain cycles")
            active_containers.add(container_id)
            stack.append((candidate, True))
            if candidate_type is dict:
                if any(type(key) is not str for key in candidate):
                    raise TypeError(f"{field_name} object keys must be strings")
                for key in reversed(candidate):
                    stack.append((candidate[key], False))
            else:
                for item in reversed(candidate):
                    stack.append((item, False))

    @classmethod
    def _validate_entry(cls, entry: MemoryEntry) -> None:
        if type(entry) is not MemoryEntry:
            raise TypeError("entry must be a MemoryEntry")
        if type(entry.type) is not MemoryType:
            raise TypeError("memory entry type must be a MemoryType")
        if not cls._is_safe_entry_id(entry.id):
            raise ValueError("memory entry id is invalid")
        for field_name in ("title", "content", "created_at", "last_accessed"):
            if type(getattr(entry, field_name)) is not str:
                raise TypeError(f"memory entry {field_name} must be a string")
        if type(entry.metadata) is not dict:
            raise TypeError("memory entry metadata must be a JSON object")
        cls._validate_json_value(entry.metadata, "memory entry metadata")
        if type(entry.tags) is not list or any(
            type(tag) is not str for tag in entry.tags
        ):
            raise TypeError("memory entry tags must be a list of strings")
        if type(entry.access_count) is not int or entry.access_count < 0:
            raise ValueError("memory entry access_count must be a non-negative integer")
        if type(entry.importance) not in (int, float) or (
            type(entry.importance) is float and not math.isfinite(entry.importance)
        ):
            raise ValueError("memory entry importance must be a finite number")
        if type(entry.token_count) is not int or entry.token_count < 0:
            raise ValueError("memory entry token_count must be a non-negative integer")
        if type(entry.compressed) is not bool:
            raise TypeError("memory entry compressed must be a boolean")
        if entry.parent_id is not None and type(entry.parent_id) is not str:
            raise TypeError("memory entry parent_id must be a string or None")
        if "probe_cleanup_token" in entry.metadata and type(
            entry.metadata["probe_cleanup_token"]
        ) is not str:
            raise TypeError("memory entry probe_cleanup_token must be a string")

    @classmethod
    def _serialize_entry(cls, entry: MemoryEntry) -> Tuple[str, bytes]:
        cls._validate_entry(entry)
        filename = f"{entry.type.value}_{entry.id}.md"
        encoder = json.JSONEncoder(
            ensure_ascii=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        try:
            probe_cleanup_token = entry.metadata.get("probe_cleanup_token", "")
            builder = _BoundedUtf8Builder(_MEMORY_ENTRY_MAX_BYTES)
            builder.append_text("---\nschema_version: 2\nid: ")
            builder.append_text(cls._frontmatter_text(entry.id))
            builder.append_text("\nname: ")
            builder.append_text(cls._frontmatter_text(entry.title))
            builder.append_text("\ndescription: ")
            builder.append_text(cls._frontmatter_text(entry.content[:100]))
            builder.append_text("\ntype: ")
            builder.append_text(cls._frontmatter_text(entry.type.value))
            builder.append_text("\nmetadata_json: ")
            builder.append_json(entry.metadata, encoder)
            builder.append_text("\ntags_json: ")
            builder.append_json(entry.tags, encoder)
            builder.append_text("\ncreated_at: ")
            builder.append_text(cls._frontmatter_text(entry.created_at))
            builder.append_text("\nlast_accessed: ")
            builder.append_text(cls._frontmatter_text(entry.last_accessed))
            builder.append_text("\naccess_count: ")
            builder.append_json(entry.access_count, encoder)
            builder.append_text("\nimportance: ")
            builder.append_json(entry.importance, encoder)
            builder.append_text("\ntoken_count: ")
            builder.append_json(entry.token_count, encoder)
            builder.append_text("\ncompressed: ")
            builder.append_json(entry.compressed, encoder)
            builder.append_text("\nparent_id: ")
            builder.append_json(entry.parent_id, encoder)
            builder.append_text("\nprobe_cleanup_token: ")
            builder.append_text(cls._frontmatter_text(probe_cleanup_token))
            builder.append_text("\n---\n\n")
            builder.append_text(entry.content)
            payload = builder.finish()
        except _MemoryPayloadTooLarge:
            raise ValueError("memory entry exceeds the size limit") from None
        except (
            OSError,
            UnicodeError,
            TypeError,
            ValueError,
            OverflowError,
            RecursionError,
        ) as error:
            raise ValueError("memory entry cannot be serialized losslessly") from error

        if len(payload) > _MEMORY_ENTRY_MAX_BYTES:
            raise ValueError("memory entry exceeds the size limit")
        try:
            decoded = cls._parse_entry(Path(filename), payload.decode("utf-8"))
        except (
            UnicodeError,
            TypeError,
            ValueError,
            OverflowError,
            RecursionError,
        ) as error:
            raise ValueError("memory entry cannot be serialized losslessly") from error
        if decoded != entry:
            raise ValueError("memory entry cannot be serialized losslessly")
        return filename, payload

    def _ensure_regular_entry_target(
        self,
        filepath: Path,
    ) -> Optional[os.stat_result]:
        try:
            entry_stat = os.lstat(filepath)
        except FileNotFoundError:
            return None
        if (
            not stat.S_ISREG(entry_stat.st_mode)
            or self._is_reparse_point(entry_stat)
        ):
            raise OSError("memory entry must be a regular file")
        return entry_stat

    def _read_existing_entry_payload(
        self,
        filepath: Path,
        expected_stat: Optional[os.stat_result],
    ) -> Optional[bytes]:
        if expected_stat is None:
            return None
        content, _ = self._read_regular_file(
            filepath,
            expected_stat,
            _MEMORY_ENTRY_MAX_BYTES,
        )
        if content is None:
            raise OSError("existing memory entry cannot be read before update")
        return content.encode("utf-8")

    def _restore_entry_after_index_failure(
        self,
        filepath: Path,
        previous_payload: Optional[bytes],
        installed_stat: os.stat_result,
    ) -> None:
        try:
            current_stat = os.lstat(filepath)
        except OSError as error:
            raise OSError("installed memory entry cannot be restored") from error
        if (
            not stat.S_ISREG(current_stat.st_mode)
            or self._is_reparse_point(current_stat)
            or not self._same_file_snapshot(installed_stat, current_stat)
        ):
            raise OSError("installed memory entry identity changed before rollback")

        if previous_payload is None:
            try:
                filepath.unlink()
            except OSError as error:
                raise OSError("new memory entry cannot be removed after failure") from error
            self._flush_parent_directory(filepath, label="memory entry rollback")
            return
        self._atomic_write_regular_target(
            filepath,
            previous_payload,
            installed_stat,
            label="memory entry rollback",
        )

    def _atomic_write_regular_target(
        self,
        filepath: Path,
        payload: bytes,
        expected_stat: Optional[os.stat_result],
        *,
        label: str,
    ) -> os.stat_result:
        temporary = filepath.with_name(
            f".{filepath.name}.{os.urandom(16).hex()}.tmp"
        )
        descriptor = None
        descriptor_was_open = False
        created_stat = None
        written_stat = None
        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        try:
            descriptor = os.open(temporary, flags, 0o600)
            descriptor_was_open = True
            opened_stat = os.fstat(descriptor)
            created_stat = opened_stat
            if (
                not stat.S_ISREG(created_stat.st_mode)
                or self._is_reparse_point(created_stat)
            ):
                raise OSError(f"{label} temporary target must be a regular file")
            temporary_stat = os.lstat(temporary)
            if (
                not stat.S_ISREG(temporary_stat.st_mode)
                or self._is_reparse_point(temporary_stat)
                or not self._same_file(created_stat, temporary_stat)
            ):
                raise OSError(f"{label} temporary target must be a regular file")

            offset = 0
            while offset < len(payload):
                written = os.write(descriptor, payload[offset : offset + 64 * 1024])
                if written <= 0:
                    raise OSError(f"{label} write made no progress")
                offset += written
            os.fsync(descriptor)
            written_stat = os.fstat(descriptor)
            if (
                not self._same_file(opened_stat, written_stat)
                or written_stat.st_size != len(payload)
            ):
                raise OSError(f"{label} temporary target changed during write")

            os.close(descriptor)
            descriptor = None
            temporary_stat = os.lstat(temporary)
            if (
                not stat.S_ISREG(temporary_stat.st_mode)
                or self._is_reparse_point(temporary_stat)
                or not self._same_file(written_stat, temporary_stat)
            ):
                raise OSError(f"{label} temporary target identity changed")

            try:
                current_stat = os.lstat(filepath)
            except FileNotFoundError:
                if expected_stat is not None:
                    raise OSError(f"{label} target disappeared before write") from None
            else:
                if (
                    expected_stat is None
                    or not stat.S_ISREG(current_stat.st_mode)
                    or self._is_reparse_point(current_stat)
                    or not self._same_file_snapshot(expected_stat, current_stat)
                ):
                    raise OSError(f"{label} target identity changed before write")

            os.replace(temporary, filepath)
            current_stat = os.lstat(filepath)
            if (
                not stat.S_ISREG(current_stat.st_mode)
                or self._is_reparse_point(current_stat)
                or not self._same_file(written_stat, current_stat)
                or current_stat.st_size != len(payload)
            ):
                raise OSError(f"{label} target identity changed after write")
            self._flush_parent_directory(filepath, label=label)
            return current_stat
        except OSError as error:
            raise OSError(f"{label} cannot be written") from error
        finally:
            if descriptor is not None:
                for _attempt in range(3):
                    try:
                        os.close(descriptor)
                    except OSError:
                        continue
                    descriptor = None
                    break
            if created_stat is not None:
                try:
                    temporary_stat = os.lstat(temporary)
                except OSError:
                    try:
                        temporary.unlink()
                    except OSError:
                        pass
                else:
                    if self._same_file(created_stat, temporary_stat):
                        try:
                            temporary.unlink()
                        except OSError:
                            pass
            elif descriptor_was_open:
                try:
                    temporary.unlink()
                except OSError:
                    pass

    def _flush_parent_directory(self, filepath: Path, *, label: str) -> None:
        """Make a completed rename or unlink durable in the containing directory."""
        try:
            fsync_directory(filepath.parent)
        except OSError as error:
            raise OSError(f"{label} directory entry cannot be flushed") from error

    @staticmethod
    def _frontmatter_text(value: Any) -> str:
        text = str(value)
        requires_encoding = (
            text != text.strip()
            or (text.startswith('"') and text.endswith('"'))
            or any(
                codepoint < 0x20
                or 0x7F <= codepoint <= 0x9F
                or codepoint in (0x2028, 0x2029)
                for codepoint in map(ord, text)
            )
        )
        if requires_encoding:
            encoded = json.dumps(text, ensure_ascii=False)
            return encoded.translate({
                0x0085: r"\u0085",
                0x2028: r"\u2028",
                0x2029: r"\u2029",
            })
        return text

    @staticmethod
    def _json_header_value(value: Any) -> str:
        return json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
            allow_nan=False,
        )

    def _update_index(self, entry: MemoryEntry, filename: str):
        with self._mutation_transaction():
            self._update_index_unlocked(entry, filename)

    @staticmethod
    def _index_inline(value: str, *, escape_label: bool = False) -> str:
        encoded = []
        for character in value:
            codepoint = ord(character)
            if character == "\\":
                encoded.append("\\\\")
            elif character == "\r":
                encoded.append("\\r")
            elif character == "\n":
                encoded.append("\\n")
            elif character == "\t":
                encoded.append("\\t")
            elif (
                codepoint < 0x20
                or 0x7F <= codepoint <= 0x9F
                or codepoint in (0x2028, 0x2029)
            ):
                encoded.append(f"\\u{codepoint:04x}")
            elif escape_label and character in "[]":
                encoded.append(f"\\{character}")
            else:
                encoded.append(character)
        return "".join(encoded)

    @staticmethod
    def _index_line_targets_filename(line: str, filename: str) -> bool:
        """Match only the Markdown link destination, never prose mentions."""
        if not line.startswith("- ["):
            return False
        label_end = None
        cursor = 3
        while cursor < len(line):
            character = line[cursor]
            if character == "\\":
                cursor += 2
                continue
            if character == "]" and cursor + 1 < len(line) and line[cursor + 1] == "(":
                label_end = cursor
                break
            cursor += 1
        if label_end is None:
            return False

        target_start = label_end + 2
        cursor = target_start
        while cursor < len(line):
            character = line[cursor]
            if character == "\\":
                cursor += 2
                continue
            if character == ")":
                return line[target_start:cursor] == filename
            cursor += 1
        return False

    def _read_index_unlocked(self) -> str:
        self._ensure_index_unlocked()
        try:
            expected_stat = os.lstat(self.index_file)
            if (
                not stat.S_ISREG(expected_stat.st_mode)
                or self._is_reparse_point(expected_stat)
            ):
                raise OSError("memory index must be a regular file")
            content, _ = self._read_regular_file(
                self.index_file,
                expected_stat,
                _MEMORY_INDEX_MAX_BYTES,
            )
        except OSError as error:
            raise OSError("memory index cannot be read") from error
        if content is None:
            raise OSError("memory index cannot be read")
        return content.replace("\r\n", "\n").replace("\r", "\n")

    def _update_index_unlocked(
        self,
        entry: MemoryEntry,
        filename: str,
        *,
        content: Optional[str] = None,
    ):
        expected_index_stat = self._ensure_regular_index_target()
        if content is None:
            content = self._read_index_unlocked()
        self._atomic_write_regular_target(
            self.index_file,
            self._render_index_update(entry, filename, content),
            expected_index_stat,
            label="memory index",
        )

    @classmethod
    def _render_index_update(
        cls,
        entry: MemoryEntry,
        filename: str,
        content: str,
    ) -> bytes:
        index_title = cls._index_inline(entry.title, escape_label=True)
        index_summary = cls._index_inline(entry.content[:100])
        index_line = f"- [{index_title}]({filename}) -- {index_summary}\n"
        index_prefix = f"- [{index_title}]("
        lines = content.split("\n")
        new_lines = []
        replaced = False
        for line in lines:
            if (
                line.startswith(index_prefix)
                or cls._index_line_targets_filename(line, filename)
            ):
                new_lines.append(index_line.strip())
                replaced = True
            else:
                new_lines.append(line)
        if replaced:
            updated = "\n".join(new_lines)
        else:
            updated = content + index_line
        try:
            payload = updated.encode("utf-8")
        except UnicodeError as error:
            raise OSError("memory index cannot be encoded") from error
        if len(payload) > _MEMORY_INDEX_MAX_BYTES:
            raise OSError("memory index exceeds the size limit")
        return payload

    @staticmethod
    def _render_index_removal(content: str, filename: str) -> bytes:
        """Drop every index row whose link destination is exactly the filename."""
        retained = [
            line
            for line in content.splitlines()
            if not MemoryStore._index_line_targets_filename(line, filename)
        ]
        payload = ("\n".join(retained) + "\n").encode("utf-8")
        if len(payload) > _MEMORY_INDEX_MAX_BYTES:
            raise OSError("memory index exceeds the size limit")
        return payload

    def _publish_entry_deletion_unlocked(
        self,
        filepath: Path,
        content: str,
        expected_index_stat: os.stat_result,
        index_content: str,
    ) -> None:
        """Journal one validated entry, unlink it, then drop its index row.

        The caller must already have validated `filepath` and read both
        `content` and `index_content` inside this store's mutation
        transaction. When the index write fails the entry is restored and the
        journal is deliberately left in place, so the next writable open
        reconciles the pair.
        """
        original_entry_payload = content.encode("utf-8")
        self._write_journal_unlocked("delete", filepath.name)
        filepath.unlink()
        self._flush_parent_directory(filepath, label="memory entry deletion")

        index_payload = self._render_index_removal(index_content, filepath.name)
        try:
            self._atomic_write_regular_target(
                self.index_file,
                index_payload,
                expected_index_stat,
                label="memory index",
            )
        except OSError as index_error:
            try:
                self._atomic_write_regular_target(
                    filepath,
                    original_entry_payload,
                    None,
                    label="memory entry rollback",
                )
            except OSError as rollback_error:
                rollback_error.add_note(f"index update also failed: {index_error}")
                raise OSError("memory entry rollback failed") from rollback_error
            raise
        self._clear_journal_unlocked()

    def _delete_entry_unlocked(self, filepath: Path) -> bool:
        """Delete one stored entry and its index row inside an open transaction.

        Returns False when the target is not a publishable entry file, has
        vanished, or cannot be read, so one unreadable record never aborts a
        batch. Index faults still propagate, because they mean the derived
        state cannot be kept consistent.
        """
        if not self._is_journalled_filename(filepath.name):
            return False
        try:
            validated_stat = os.lstat(filepath)
        except OSError:
            return False
        if (
            not stat.S_ISREG(validated_stat.st_mode)
            or self._is_reparse_point(validated_stat)
        ):
            return False
        content = self._read_regular_candidate(filepath, normalize_newlines=False)
        if content is None:
            return False

        expected_index_stat = self._ensure_regular_index_target()
        index_content = self._read_index_unlocked()

        try:
            current_stat = os.lstat(filepath)
        except OSError:
            return False
        if (
            not stat.S_ISREG(current_stat.st_mode)
            or self._is_reparse_point(current_stat)
            or not self._same_file_snapshot(validated_stat, current_stat)
        ):
            return False

        self._publish_entry_deletion_unlocked(
            filepath,
            content,
            expected_index_stat,
            index_content,
        )
        return True

    def delete_probe(
        self,
        memory_type: MemoryType,
        entry_id: str,
        cleanup_token: str,
    ) -> bool:
        """Delete an integration probe after exact type, title, and token checks."""
        with self._mutation_transaction():
            return self._delete_probe_unlocked(memory_type, entry_id, cleanup_token)

    def _delete_probe_unlocked(
        self,
        memory_type: MemoryType,
        entry_id: str,
        cleanup_token: str,
    ) -> bool:
        if not isinstance(memory_type, MemoryType):
            return False
        if not self._is_safe_entry_id(entry_id):
            return False
        if not isinstance(cleanup_token, str) or not cleanup_token:
            return False

        filepath = self.memory_dir / f"{memory_type.value}_{entry_id}.md"
        try:
            validated_stat = os.lstat(filepath)
        except OSError:
            return False
        if (
            not stat.S_ISREG(validated_stat.st_mode)
            or self._is_reparse_point(validated_stat)
        ):
            return False
        content = self._read_regular_candidate(filepath, normalize_newlines=False)
        if content is None:
            return False

        try:
            raw_parsed = self._parse_frontmatter_raw(content, decode_values=False)
        except (
            OSError,
            UnicodeError,
            TypeError,
            ValueError,
            OverflowError,
            RecursionError,
        ):
            return False
        if raw_parsed is None:
            return False

        raw_metadata, _ = raw_parsed
        if "schema_version" in raw_metadata:
            try:
                entry = self._parse_entry(filepath, content)
            except (
                OSError,
                UnicodeError,
                TypeError,
                ValueError,
                OverflowError,
                RecursionError,
            ):
                return False
            if entry is None or entry.type is not memory_type:
                return False
            title = entry.title
            stored_token = entry.metadata.get("probe_cleanup_token", "")
        else:
            try:
                parsed = self._parse_frontmatter(content)
            except (
                OSError,
                UnicodeError,
                TypeError,
                ValueError,
                OverflowError,
                RecursionError,
            ):
                return False
            if parsed is None:
                return False
            metadata, _ = parsed
            try:
                declared_type = MemoryType(metadata.get("type", "user"))
            except (TypeError, ValueError):
                return False
            if declared_type is not memory_type:
                return False
            title = metadata.get("name", "")
            stored_token = metadata.get("probe_cleanup_token", "")

        if not title.startswith(".test-local-integration-"):
            return False
        if not stored_token or not hmac.compare_digest(stored_token, cleanup_token):
            return False

        try:
            expected_index_stat = self._ensure_regular_index_target()
            index_content = self._read_index_unlocked()
        except OSError:
            return False

        try:
            current_stat = os.lstat(filepath)
        except OSError:
            return False
        if (
            not stat.S_ISREG(current_stat.st_mode)
            or self._is_reparse_point(current_stat)
            or not self._same_file_snapshot(validated_stat, current_stat)
        ):
            return False

        self._publish_entry_deletion_unlocked(
            filepath,
            content,
            expected_index_stat,
            index_content,
        )
        return True

    @staticmethod
    def _bounded_positive(value: Optional[int], name: str) -> Optional[int]:
        if value is not None and (type(value) is not int or value < 1):
            raise ValueError(f"{name} must be a positive integer or None")
        return value

    @staticmethod
    def _is_reparse_point(file_stat: os.stat_result) -> bool:
        attributes = getattr(file_stat, "st_file_attributes", 0)
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        return bool(attributes & reparse_flag)

    @staticmethod
    def _same_file(left: os.stat_result, right: os.stat_result) -> bool:
        return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)

    @classmethod
    def _same_file_snapshot(
        cls,
        left: os.stat_result,
        right: os.stat_result,
    ) -> bool:
        return (
            cls._same_file(left, right)
            and stat.S_IFMT(left.st_mode) == stat.S_IFMT(right.st_mode)
            and left.st_size == right.st_size
            and getattr(left, "st_mtime_ns", None)
            == getattr(right, "st_mtime_ns", None)
            and getattr(left, "st_ctime_ns", None)
            == getattr(right, "st_ctime_ns", None)
        )

    def _read_regular_file(
        self,
        filepath: Path,
        expected_stat: os.stat_result,
        byte_limit: int,
    ) -> Tuple[Optional[str], int]:
        flags = (
            os.O_RDONLY
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        try:
            descriptor = os.open(filepath, flags)
        except OSError:
            return None, 0
        consumed = 0
        try:
            opened_stat = os.fstat(descriptor)
            if (
                not stat.S_ISREG(opened_stat.st_mode)
                or self._is_reparse_point(opened_stat)
                or not self._same_file(expected_stat, opened_stat)
                or opened_stat.st_size > byte_limit
            ):
                return None, 0
            chunks = []
            remaining = opened_stat.st_size
            while remaining:
                chunk = os.read(descriptor, min(remaining, 64 * 1024))
                if not chunk:
                    break
                chunks.append(chunk)
                consumed += len(chunk)
                remaining -= len(chunk)
            final_stat = os.fstat(descriptor)
            if (
                remaining
                or final_stat.st_size != opened_stat.st_size
                or not self._same_file(opened_stat, final_stat)
            ):
                return None, consumed
            try:
                return b"".join(chunks).decode("utf-8"), consumed
            except UnicodeDecodeError:
                return None, consumed
        except OSError:
            return None, consumed
        finally:
            os.close(descriptor)

    def _read_regular_candidate(
        self,
        filepath: Path,
        *,
        normalize_newlines: bool = True,
    ) -> Optional[str]:
        try:
            expected_stat = os.lstat(filepath)
            if (
                not stat.S_ISREG(expected_stat.st_mode)
                or self._is_reparse_point(expected_stat)
            ):
                return None
            content, _ = self._read_regular_file(
                filepath,
                expected_stat,
                min(expected_stat.st_size, _MEMORY_ENTRY_MAX_BYTES),
            )
            if content is None:
                return None
            if normalize_newlines:
                return content.replace("\r\n", "\n").replace("\r", "\n")
            return content
        except OSError:
            return None

    @staticmethod
    def _decode_frontmatter_text(value: str) -> str:
        value = value.strip()
        if value.startswith('"') and value.endswith('"'):
            decoded = json.loads(value)
            if type(decoded) is not str:
                raise ValueError("frontmatter string must decode to text")
            return decoded
        return value

    @classmethod
    def _parse_frontmatter_raw(
        cls,
        content: str,
        *,
        decode_values: bool = True,
    ) -> Optional[Tuple[Dict[str, str], str]]:
        lines = content.splitlines(keepends=True)
        if not lines or lines[0].rstrip("\r\n") != "---":
            return None
        closing_index = next(
            (
                index
                for index, line in enumerate(lines[1:], start=1)
                if line.rstrip("\r\n") == "---"
            ),
            None,
        )
        if closing_index is None:
            return None
        metadata: Dict[str, str] = {}
        invalid_header_line = False
        for line in lines[1:closing_index]:
            line = line.rstrip("\r\n")
            if ":" in line:
                key, value = line.split(":", 1)
                key = key.strip()
                if not key or key in metadata:
                    raise ValueError("frontmatter keys must be unique")
                raw_value = value.strip()
                metadata[key] = (
                    cls._decode_frontmatter_text(raw_value)
                    if decode_values
                    else raw_value
                )
            else:
                invalid_header_line = True
        if "schema_version" in metadata and invalid_header_line:
            raise ValueError("versioned frontmatter requires one field per line")
        body_start = sum(len(line) for line in lines[:closing_index + 1])
        body = content[body_start:]
        if body.startswith("\r\n"):
            body = body[2:]
        elif body.startswith(("\n", "\r")):
            body = body[1:]
        return metadata, body

    @classmethod
    def _parse_frontmatter(
        cls, content: str
    ) -> Optional[Tuple[Dict[str, str], str]]:
        parsed = cls._parse_frontmatter_raw(content)
        if parsed is None:
            return None
        metadata, body = parsed
        normalized = body.replace("\r\n", "\n").replace("\r", "\n")
        return metadata, normalized.strip()

    @classmethod
    def _parse_json_header_value(cls, value: str) -> Any:
        try:
            return json.loads(
                value,
                object_pairs_hook=_reject_duplicate_json_keys,
                parse_constant=_reject_json_constant,
            )
        except (TypeError, ValueError, json.JSONDecodeError, RecursionError) as error:
            raise ValueError("memory entry JSON header value is invalid") from error

    @staticmethod
    def _entry_id_from_path(filepath: Path) -> str:
        stem = filepath.stem
        for memory_type in MemoryType:
            prefix = f"{memory_type.value}_"
            if stem.startswith(prefix):
                return stem[len(prefix):]
        return stem

    @staticmethod
    def _parse_legacy_bool(value: str) -> bool:
        normalized = value.strip().lower()
        if normalized == "true":
            return True
        if normalized == "false":
            return False
        raise ValueError("legacy boolean value is invalid")

    @staticmethod
    def _parse_legacy_line(value: str, prefix: str) -> Optional[Tuple[str, str]]:
        if not value.startswith(prefix):
            return None
        end = value.find("\n")
        if end < 0:
            return value[len(prefix):], ""
        return value[len(prefix):end], value[end + 1:]

    @classmethod
    def _parse_legacy_footer(
        cls,
        body: str,
        frontmatter: Dict[str, str],
    ) -> Optional[Tuple[str, Dict[str, Any]]]:
        """Recover a complete, unambiguous footer from the original format."""
        marker = "**metadata**: "
        decoder = json.JSONDecoder(
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=_reject_json_constant,
        )
        # The five scalar footer lines are fixed and always terminate the
        # legacy record. Locate them from the end once, then decode JSON in
        # place. This keeps malformed marker-rich bodies linear instead of
        # repeatedly copying and rescanning the remaining suffix.
        cursor = len(body)
        while cursor and body[cursor - 1].isspace():
            cursor -= 1
        values: Dict[str, str] = {}
        tags_line_start = None
        for key, prefix in (
            ("importance", "**importance**: "),
            ("access_count", "**access_count**: "),
            ("last_accessed", "**last_accessed**: "),
            ("created_at", "**created**: "),
            ("tags", "**tags**: "),
        ):
            line_start = body.rfind("\n", 0, cursor) + 1
            line = body[line_start:cursor]
            if line.endswith("\r"):
                line = line[:-1]
            if not line.startswith(prefix):
                return None
            values[key] = line[len(prefix):]
            if key == "tags":
                tags_line_start = line_start
            cursor = line_start
            if cursor and body[cursor - 1] == "\n":
                cursor -= 1

        if tags_line_start is None:
            return None
        marker_pattern = re.compile(r"(?m)^\*\*metadata\*\*: ")
        marker_start = None
        for match in marker_pattern.finditer(body, 0, cursor):
            marker_start = match.start()
        if marker_start is None:
            return None

        json_start = marker_start + len(marker)
        while json_start < cursor and body[json_start] in " \t":
            json_start += 1
        try:
            footer_metadata, consumed = decoder.raw_decode(body, json_start)
        except (TypeError, ValueError, json.JSONDecodeError, RecursionError):
            return None
        if type(footer_metadata) is not dict:
            return None
        try:
            cls._validate_json_value(footer_metadata, "legacy memory metadata")
        except (TypeError, ValueError):
            return None
        if body[consumed:tags_line_start] not in ("\n", "\r\n"):
            return None

        # This is the original encoder's delimiter. A legacy tag that itself
        # contained `, ` remains inherently ambiguous.
        tags_text = values["tags"]
        tags = [] if not tags_text else tags_text.split(", ")
        try:
            access_count = int(values["access_count"].strip())
            importance = float(values["importance"].strip())
        except (TypeError, ValueError, OverflowError):
            return None
        if access_count < 0 or not math.isfinite(importance):
            return None

        stored_token = frontmatter.get("probe_cleanup_token", "")
        footer_token = footer_metadata.get("probe_cleanup_token")
        if "probe_cleanup_token" in footer_metadata and (
            type(footer_token) is not str or footer_token != stored_token
        ):
            return None
        if stored_token and "probe_cleanup_token" not in footer_metadata:
            return None
        return body[:marker_start].rstrip(), {
            "metadata": footer_metadata,
            "tags": tags,
            "created_at": values["created_at"],
            "last_accessed": values["last_accessed"],
            "access_count": access_count,
            "importance": importance,
        }

    @classmethod
    def _parse_v2_entry(
        cls,
        filepath: Path,
        metadata: Dict[str, str],
        body: str,
    ) -> Optional[MemoryEntry]:
        allowed_fields = _MEMORY_ENTRY_V2_REQUIRED_FIELDS | _MEMORY_ENTRY_V2_OPTIONAL_FIELDS
        if (
            set(metadata) - allowed_fields
            or not _MEMORY_ENTRY_V2_REQUIRED_FIELDS.issubset(metadata)
        ):
            return None
        schema_version = cls._parse_json_header_value(metadata["schema_version"])
        if type(schema_version) is not int or schema_version != _MEMORY_ENTRY_SCHEMA_VERSION:
            return None

        entry_id = cls._decode_frontmatter_text(metadata["id"])
        if not cls._is_safe_entry_id(entry_id):
            return None

        memory_type_text = cls._decode_frontmatter_text(metadata["type"])
        try:
            memory_type = MemoryType(memory_type_text)
        except (TypeError, ValueError):
            return None
        if filepath.name != f"{memory_type.value}_{entry_id}.md":
            return None

        title = cls._decode_frontmatter_text(metadata["name"])
        if type(title) is not str:
            return None
        if "description" in metadata:
            cls._decode_frontmatter_text(metadata["description"])

        record_metadata = cls._parse_json_header_value(metadata["metadata_json"])
        if type(record_metadata) is not dict:
            return None
        try:
            cls._validate_json_value(record_metadata, "memory entry metadata")
        except (TypeError, ValueError):
            return None
        tags = cls._parse_json_header_value(metadata["tags_json"])
        if type(tags) is not list or any(type(tag) is not str for tag in tags):
            return None

        created_at = cls._decode_frontmatter_text(metadata["created_at"])
        last_accessed = cls._decode_frontmatter_text(metadata["last_accessed"])
        if type(created_at) is not str or type(last_accessed) is not str:
            return None

        access_count = cls._parse_json_header_value(metadata["access_count"])
        if type(access_count) is not int or access_count < 0:
            return None
        importance = cls._parse_json_header_value(metadata["importance"])
        if type(importance) not in (int, float) or not math.isfinite(importance):
            return None
        token_count = cls._parse_json_header_value(metadata["token_count"])
        if type(token_count) is not int or token_count < 0:
            return None
        compressed = cls._parse_json_header_value(metadata["compressed"])
        if type(compressed) is not bool:
            return None
        parent_id = cls._parse_json_header_value(metadata["parent_id"])
        if parent_id is not None and type(parent_id) is not str:
            return None

        probe_cleanup_token = cls._decode_frontmatter_text(
            metadata["probe_cleanup_token"]
        )
        if type(probe_cleanup_token) is not str:
            return None
        embedded_token = record_metadata.get("probe_cleanup_token")
        if "probe_cleanup_token" in record_metadata and (
            type(embedded_token) is not str or embedded_token != probe_cleanup_token
        ):
            return None
        if probe_cleanup_token and "probe_cleanup_token" not in record_metadata:
            return None

        return MemoryEntry(
            id=entry_id,
            type=memory_type,
            title=title,
            content=body,
            metadata=record_metadata,
            created_at=created_at,
            last_accessed=last_accessed,
            access_count=access_count,
            tags=tags,
            importance=importance,
            token_count=token_count,
            compressed=compressed,
            parent_id=parent_id,
        )

    @classmethod
    def _parse_entry(cls, filepath: Path, content: str) -> Optional[MemoryEntry]:
        parsed = cls._parse_frontmatter_raw(content, decode_values=False)
        if parsed is None:
            return None
        raw_metadata, raw_body = parsed
        if "schema_version" in raw_metadata:
            return cls._parse_v2_entry(filepath, raw_metadata, raw_body)

        metadata = {
            key: cls._decode_frontmatter_text(value)
            for key, value in raw_metadata.items()
        }

        body = raw_body.replace("\r\n", "\n").replace("\r", "\n").strip()
        memory_type = MemoryType(metadata.get("type", "user"))
        title = metadata.get("name", filepath.stem)
        footer = cls._parse_legacy_footer(body, metadata)
        if footer is None:
            footer_metadata = metadata
            tags: List[str] = []
            created_at = metadata.get("created", "")
            last_accessed = metadata.get("last_accessed", "")
            access_count = int(metadata.get("access_count", 0))
            importance = float(metadata.get("importance", 0.5))
            content_body = body
        else:
            content_body, footer_values = footer
            footer_metadata = footer_values["metadata"]
            tags = footer_values["tags"]
            created_at = footer_values["created_at"]
            last_accessed = footer_values["last_accessed"]
            access_count = footer_values["access_count"]
            importance = footer_values["importance"]
        compressed = cls._parse_legacy_bool(metadata.get("compressed", "false"))
        parent_id = metadata.get("parent_id")
        return MemoryEntry(
            id=cls._entry_id_from_path(filepath),
            type=memory_type,
            title=title,
            content=content_body,
            metadata=footer_metadata,
            created_at=created_at,
            last_accessed=last_accessed,
            access_count=access_count,
            tags=tags,
            importance=importance,
            token_count=int(metadata.get("token_count", 0)),
            compressed=compressed,
            parent_id=parent_id,
        )

    def load(
        self,
        memory_type: Optional[MemoryType] = None,
        *,
        max_directory_entries: Optional[int] = None,
        max_files: Optional[int] = None,
        max_file_bytes: Optional[int] = None,
        max_total_bytes: Optional[int] = None,
    ) -> List[MemoryEntry]:
        limits = {
            "max_directory_entries": self._bounded_positive(
                max_directory_entries, "max_directory_entries"
            ),
            "max_files": self._bounded_positive(max_files, "max_files"),
            "max_file_bytes": self._bounded_positive(
                max_file_bytes, "max_file_bytes"
            ),
            "max_total_bytes": self._bounded_positive(
                max_total_bytes, "max_total_bytes"
            ),
        }
        if not self.read_only:
            if any(value is not None for value in limits.values()):
                raise ValueError("load limits are available only in read-only mode")
            with self._mutation_transaction():
                return self._load_legacy(memory_type)
        return self._load_read_only(memory_type, **limits)

    def _load_legacy(self, memory_type: Optional[MemoryType]) -> List[MemoryEntry]:
        return [entry for _filepath, entry in self._bounded_legacy_records(memory_type)]

    def _bounded_legacy_records(
        self,
        memory_type: Optional[MemoryType] = None,
    ) -> List[Tuple[Path, MemoryEntry]]:
        """Pair every parseable entry with the file it was actually read from.

        Consolidation needs the real source path: a record whose frontmatter
        type disagrees with its filename prefix does not round-trip to the same
        name, so reconstructing the name from the entry alone would target the
        wrong file.
        """
        records: List[Tuple[Path, MemoryEntry]] = []
        for filepath in self._bounded_legacy_candidates():
            if filepath.name == "MEMORY.md":
                continue
            content = self._read_regular_candidate(filepath, normalize_newlines=False)
            if content is None:
                continue
            try:
                entry = self._parse_entry(filepath, content)
            except (
                OSError,
                UnicodeError,
                TypeError,
                ValueError,
                OverflowError,
                RecursionError,
            ):
                continue
            if entry is not None and (memory_type is None or entry.type == memory_type):
                records.append((filepath, entry))
        return records

    def _bounded_legacy_candidates(self) -> List[Path]:
        """Collect a complete, bounded direct-entry snapshot for legacy loads."""
        candidates: List[Path] = []
        try:
            with os.scandir(self.memory_dir) as scanner:
                for candidate in scanner:
                    if len(candidates) >= _MEMORY_LEGACY_DIRECTORY_ENTRIES:
                        return []
                    candidates.append(Path(candidate.path))
        except (OSError, TypeError, ValueError, OverflowError):
            return []
        candidates.sort(key=lambda path: path.name)
        return candidates

    def _load_read_only(
        self,
        memory_type: Optional[MemoryType],
        *,
        max_directory_entries: Optional[int],
        max_files: Optional[int],
        max_file_bytes: Optional[int],
        max_total_bytes: Optional[int],
    ) -> List[MemoryEntry]:
        try:
            root_stat = os.lstat(self.memory_dir)
            if (
                not stat.S_ISDIR(root_stat.st_mode)
                or self._is_reparse_point(root_stat)
            ):
                return []
            with os.scandir(self.memory_dir) as scanner:
                candidates = list(islice(scanner, max_directory_entries))
        except OSError:
            return []

        entries = []
        files_seen = 0
        total_bytes = 0
        for candidate in sorted(candidates, key=lambda item: item.name):
            if candidate.name == "MEMORY.md" or not candidate.name.endswith(".md"):
                continue
            if max_files is not None and files_seen >= max_files:
                break
            files_seen += 1
            try:
                if (
                    candidate.is_symlink()
                    or not candidate.is_file(follow_symlinks=False)
                ):
                    continue
                candidate_stat = os.lstat(candidate.path)
            except OSError:
                continue
            if self._is_reparse_point(candidate_stat):
                continue
            remaining_total = (
                max_total_bytes - total_bytes
                if max_total_bytes is not None
                else candidate_stat.st_size
            )
            allowed_bytes = min(
                candidate_stat.st_size if max_file_bytes is None else max_file_bytes,
                remaining_total,
            )
            if candidate_stat.st_size > allowed_bytes:
                continue
            content, consumed = self._read_regular_file(
                Path(candidate.path),
                candidate_stat,
                allowed_bytes,
            )
            total_bytes += consumed
            if content is None:
                continue
            try:
                entry = self._parse_entry(Path(candidate.path), content)
            except (TypeError, ValueError, OverflowError, RecursionError):
                continue
            if entry is not None and (memory_type is None or entry.type == memory_type):
                entries.append(entry)
        return entries

    def consolidate(self) -> Dict[str, int]:
        """记忆整合 — 合并重复、清理过期、语义压缩"""
        with self._mutation_transaction():
            return self._consolidate_unlocked()

    def _consolidate_unlocked(self) -> Dict[str, int]:
        records = self._bounded_legacy_records()
        entries = [entry for _filepath, entry in records]
        stats = {
            "total": len(entries),
            "merged": 0,
            "pruned": 0,
            "compressed": 0,
            "remaining": 0,
            "removed": 0,
            "tokens_saved": 0,
        }

        # 使用语义压缩器进行基于重要性的压缩
        compressed, compress_stats = self.compressor.compress(entries)
        stats["compressed"] = compress_stats["summarized"]
        stats["pruned"] = compress_stats["pruned"]
        stats["merged"] = compress_stats["merged"]
        stats["tokens_saved"] = compress_stats["tokens_saved"]
        stats["remaining"] = len(compressed)

        # 先写入压缩结果，再删除未存活记录：合并后的存活记录携带被吸收记录的
        # 内容，所以删除必须发生在替代内容持久化之后。
        # Every store and every deletion below is individually journalled, so a
        # crash mid-batch leaves an applied prefix whose entry/index pairs are
        # all consistent. Storing first makes that prefix a superset of the
        # final state, so re-running consolidate converges without ever losing
        # a body the merge had already folded into a survivor.
        for entry in compressed:
            self._store_unlocked(entry)

        # 压缩保留 id，所以存活文件名可直接比对；存活集合与删除集合互斥。
        surviving = {f"{entry.type.value}_{entry.id}.md" for entry in compressed}
        for filepath, _entry in records:
            if filepath.name in surviving:
                continue
            if self._delete_entry_unlocked(filepath):
                stats["removed"] += 1

        return stats

    def get_stats(self) -> Dict[str, Any]:
        """获取记忆统计"""
        entries = self.load()
        stats = {
            "total": len(entries),
            "by_type": {},
            "total_tokens": 0,
            "compressed_count": 0,
            "avg_importance": 0.0,
        }

        for entry in entries:
            type_name = entry.type.value
            stats["by_type"][type_name] = stats["by_type"].get(type_name, 0) + 1
            stats["total_tokens"] += entry.token_count
            if entry.compressed:
                stats["compressed_count"] += 1

        if entries:
            stats["avg_importance"] = sum(e.importance for e in entries) / len(entries)

        return stats


class LLMCompressor:
    """LLM-driven context compressor - Phase 11 capability.

    Uses local Ollama model for semantic compression (dependency-injected OllamaManager,
    does NOT directly import kernel). Falls back to SemanticCompressor (heuristic) when
    Ollama is unavailable.
    """

    def __init__(self, ollama_manager=None, model: str = "llama3.2",
                 token_budget: int = 4000):
        self.ollama_manager = ollama_manager
        self.model = model
        self.token_budget = token_budget
        self._fallback = SemanticCompressor(token_budget=token_budget)
        self._compression_history_lock = threading.Lock()
        self._compression_history: deque[Dict[str, Any]] = deque(
            maxlen=LLM_COMPRESSION_HISTORY_LIMIT
        )

    def compress_entries(self, entries: List[MemoryEntry]) -> Tuple[List[MemoryEntry], Dict[str, Any]]:
        """Compress a list of memory entries. Returns (compressed_list, stats_dict)."""
        if not entries:
            return [], {"total": 0, "llm_summarized": 0, "heuristic_summarized": 0,
                        "pruned": 0, "tokens_saved": 0, "remaining": 0, "llm_available": False}

        if self.ollama_manager is None:
            return self._compress_fallback(entries)

        llm_summarized = 0
        heuristic_count = 0
        tokens_saved = 0
        kept: List[MemoryEntry] = []
        current_tokens = 0

        for entry in sorted(entries, key=lambda e: e.importance, reverse=True):
            if self._is_expired(entry) and entry.importance < 0.5:
                tokens_saved += entry.token_count
                self._record(entry, "pruned")
                continue

            if current_tokens + entry.token_count > self.token_budget:
                if entry.importance >= 0.7:
                    compressed = self._llm_summarize(entry)
                    if compressed is not None:
                        kept.append(compressed)
                        llm_summarized += 1
                        tokens_saved += entry.token_count - compressed.token_count
                        current_tokens += compressed.token_count
                        self._record(entry, "llm_summarized")
                        continue
                if entry.importance >= 0.3:
                    compressed = self._heuristic_summarize(entry)
                    kept.append(compressed)
                    heuristic_count += 1
                    tokens_saved += entry.token_count - compressed.token_count
                    current_tokens += compressed.token_count
                    self._record(entry, "heuristic_summarized")
                    continue
                tokens_saved += entry.token_count
                self._record(entry, "pruned")
                continue

            kept.append(entry)
            current_tokens += entry.token_count

        merged = self._merge_duplicates(kept)
        stats = {
            "total": len(entries),
            "llm_summarized": llm_summarized,
            "heuristic_summarized": heuristic_count,
            "pruned": len(entries) - len(merged),
            "tokens_saved": tokens_saved,
            "remaining": len(merged),
            "llm_available": True,
        }
        return merged, stats

    def _compress_fallback(self, entries: List[MemoryEntry]) -> Tuple[List[MemoryEntry], Dict[str, Any]]:
        """Pure heuristic compression (when Ollama unavailable)."""
        result, stats = self._fallback.compress(entries)
        stats["llm_available"] = False
        for e in entries:
            self._record(e, "fallback")
        return result, stats

    def _llm_summarize(self, entry: MemoryEntry) -> Optional[MemoryEntry]:
        """Call Ollama for summarization. Returns None on failure."""
        if self.ollama_manager is None:
            return None
        prompt = (
            "请用中文简要总结以下内容，保留关键决策、版本号、路径和约束条件。\n"
            f"TITLE: {entry.title}\nCONTENT: {entry.content[:800]}"
        )
        try:
            resp = self.ollama_manager.chat(model=self.model, messages=[
                {"role": "user", "content": prompt}
            ], stream=False)
            summary_text = resp.get("message", {}).get("content", "").strip()
            if not summary_text:
                return None
            return MemoryEntry(
                id=entry.id, type=entry.type,
                title=_marked_title(entry.title, " [llm-summary]"),
                content=f"[LLM Summary] {summary_text}",
                metadata={**entry.metadata, "llm_summarized": True},
                created_at=entry.created_at, last_accessed=entry.last_accessed,
                access_count=entry.access_count, tags=entry.tags,
                importance=entry.importance * 0.95,
                token_count=MemoryEntry._estimate_tokens(summary_text),
                compressed=True, parent_id=entry.id,
            )
        except Exception:
            return None

    def _heuristic_summarize(self, entry: MemoryEntry) -> MemoryEntry:
        """Heuristic summarization (same as SemanticCompressor._summarize)."""
        content = entry.content
        sentences = re.split(r'[。.!?\n]', content)
        sentences = [s.strip() for s in sentences if s.strip()]
        keywords = ["decided", "chosen", "must", "should", "constraint", "constraint"]
        key_sentences = [s for s in sentences if any(kw in s.lower() for kw in keywords)]
        summary_text = "; ".join(key_sentences[:3]) if key_sentences else "; ".join(sentences[:3])
        summary_text = f"[summary] {summary_text}" if summary_text else "[summary] compressed"
        return MemoryEntry(
            id=entry.id, type=entry.type,
            title=_marked_title(entry.title, " [summary]"),
            content=summary_text, metadata={**entry.metadata, "summarized": True},
            created_at=entry.created_at, last_accessed=entry.last_accessed,
            access_count=entry.access_count, tags=entry.tags,
            importance=entry.importance * 0.9,
            token_count=MemoryEntry._estimate_tokens(summary_text),
            compressed=True, parent_id=entry.id,
        )

    @staticmethod
    def _is_expired(entry: MemoryEntry) -> bool:
        if entry.access_count >= 5:
            return False
        try:
            last_accessed = datetime.fromisoformat(entry.last_accessed)
            return last_accessed < datetime.now() - timedelta(days=30)
        except (ValueError, TypeError):
            return False

    @staticmethod
    def _merge_duplicates(entries: List[MemoryEntry]) -> List[MemoryEntry]:
        """Match on the base title so a summarized record still collides.

        This compressor's output never drives a disk deletion, so it keeps the
        selecting shape rather than the absorbing fold that `SemanticCompressor`
        uses. It does need the same marker-insensitive matching, otherwise a
        record summarized on an earlier pass silently stops deduplicating.
        """
        seen_titles: Dict[str, MemoryEntry] = {}
        merged: List[MemoryEntry] = []
        for entry in entries:
            key = _base_title(entry.title)
            if key in seen_titles:
                existing = seen_titles[key]
                if entry.access_count > existing.access_count:
                    merged = [e for e in merged if e.id != existing.id]
                    merged.append(entry)
                    seen_titles[key] = entry
            else:
                seen_titles[key] = entry
                merged.append(entry)
        return merged

    def _record(self, entry: MemoryEntry, action: str):
        record = {
            "entry_id": entry.id, "title": entry.title,
            "action": action, "tokens": entry.token_count,
            "timestamp": datetime.now().isoformat(),
        }
        with self._compression_history_lock:
            self._compression_history.append(record)

    @property
    def compression_history(self) -> List[Dict[str, Any]]:
        with self._compression_history_lock:
            return [dict(record) for record in self._compression_history]

    def clear_history(self):
        with self._compression_history_lock:
            self._compression_history.clear()


class AdaptiveContextCompressor(ContextCompressor):
    """Adaptive context compressor - auto-selects strategy based on conversation length ratio.

    Ratio < 0.3: NONE (no compression)
    Ratio 0.3-0.7: TRUNCATE (truncate early messages)
    Ratio 0.7-1.0: SUMMARIZE (summarize older messages)
    Ratio > 1.0: SEMANTIC (importance-based elimination)
    """

    def __init__(self, max_tokens: int = 4000, ollama_manager=None,
                 llm_model: str = "llama3.2"):
        super().__init__(max_tokens=max_tokens)
        self.llm_compressor = LLMCompressor(
            ollama_manager=ollama_manager, model=llm_model, token_budget=max_tokens
        )

    def compress(self, conversation: List[Dict[str, str]]) -> str:
        if not conversation:
            return ""
        total_chars = sum(len(str(m.get("content", ""))) for m in conversation)
        ratio = total_chars / (self.max_tokens * 4)
        if ratio < 0.3:
            return self._format_conversation(conversation)
        if ratio < 0.7:
            return self._truncate_recent(conversation)
        if ratio <= 1.0:
            older = conversation[:-3]
            recent = conversation[-3:]
            summary = self._summarize(older)
            return f"[SUMMARY] {summary}\n\n[RECENT]\n{self._format_conversation(recent)}"
        return self._semantic_compress(conversation)

    def _truncate_recent(self, conversation: List[Dict[str, str]]) -> str:
        lines = []
        for m in conversation:
            content = m.get("content", "")
            truncated_content = content[:200] + ("..." if len(content) > 200 else "")
            lines.append(m.get("role", "?") + ": " + truncated_content)
        return "\n".join(lines)


    def _semantic_compress(self, conversation: List[Dict[str, str]]) -> str:
        entries = [
            MemoryEntry.create(
                MemoryType.USER if m.get("role") == "user" else MemoryType.PROJECT,
                f"msg_{i}", m.get("content", "")[:500],
                importance=0.5 + (i / max(len(conversation), 1)) * 0.5,
            )
            for i, m in enumerate(conversation)
        ]
        compressed, _ = self.llm_compressor.compress_entries(entries)
        return "\n".join(f"[{e.type.value}] {e.title}: {e.content[:200]}" for e in compressed[:10])


def main():
    import sys
    if len(sys.argv) < 2:
        print("Usage: python context_compressor.py <command>")
        print("  compress <conversation.json>  Compress conversation history")
        print("  store <type> <title> <content> [importance]  Store memory")
        print("  consolidate                   Consolidate memories")
        print("  stats                         Memory statistics")
        print("  list [type]                   List memories")
        sys.exit(1)

    command = sys.argv[1]
    if command == "compress":
        if len(sys.argv) < 3:
            print("Usage: python context_compressor.py compress <conversation.json>")
            sys.exit(1)
        conversation = read_bounded_json(sys.argv[2], label="conversation JSON input")
        compressor = ContextCompressor()
        print(compressor.compress(conversation))
    elif command == "store":
        if len(sys.argv) < 5:
            print("Usage: python context_compressor.py store <type> <title> <content> [importance]")
            sys.exit(1)
        memory_type = MemoryType(sys.argv[2])
        importance = float(sys.argv[5]) if len(sys.argv) > 5 else 0.5
        entry = MemoryEntry.create(memory_type, sys.argv[3], sys.argv[4], importance=importance)
        store = MemoryStore()
        print(f"Stored: {store.store(entry)}")
    elif command == "consolidate":
        store = MemoryStore()
        print(json.dumps(store.consolidate(), indent=2, ensure_ascii=False))
    elif command == "stats":
        store = MemoryStore()
        print(json.dumps(store.get_stats(), indent=2, ensure_ascii=False))
    elif command == "list":
        memory_type = MemoryType(sys.argv[2]) if len(sys.argv) >= 3 else None
        store = MemoryStore()
        entries = store.load(memory_type)
        print(f"Total {len(entries)} memories:")
        for entry in entries:
            print(f"  [{entry.type.value}] {entry.title} (accessed {entry.access_count} times, importance {entry.importance:.2f})")
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
