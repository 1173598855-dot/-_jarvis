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
import os
import re
import stat
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from itertools import islice
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class MemoryType(Enum):
    USER = "user"
    FEEDBACK = "feedback"
    PROJECT = "project"
    REFERENCE = "reference"


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
        content = entry.content
        split_point = int(len(content) * 0.6)
        truncated_content = (
            content[:split_point]
            + "\n... [truncated, see original record for full content] ...\n"
            + content[-int(len(content) * 0.4):]
        )
        return MemoryEntry(
            id=entry.id, type=entry.type, title=entry.title + " [truncated]",
            content=truncated_content, metadata={**entry.metadata, "truncated": True},
            created_at=entry.created_at, last_accessed=entry.last_accessed,
            access_count=entry.access_count, tags=entry.tags,
            importance=entry.importance,
            token_count=MemoryEntry._estimate_tokens(truncated_content),
            compressed=True, parent_id=entry.id,
        )

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
            id=entry.id, type=entry.type, title=entry.title + " [summary]",
            content=summary, metadata={**entry.metadata, "summarized": True, "original_length": len(content)},
            created_at=entry.created_at, last_accessed=entry.last_accessed,
            access_count=entry.access_count, tags=entry.tags,
            importance=entry.importance * 0.9,
            token_count=MemoryEntry._estimate_tokens(summary),
            compressed=True, parent_id=entry.id,
        )

    def _merge_duplicates(self, entries: List[MemoryEntry]) -> List[MemoryEntry]:
        seen_titles = {}
        merged = []
        for entry in entries:
            if entry.title in seen_titles:
                existing = seen_titles[entry.title]
                if entry.access_count > existing.access_count:
                    merged = [e for e in merged if e.id != existing.id]
                    merged.append(entry)
                    seen_titles[entry.title] = entry
            else:
                seen_titles[entry.title] = entry
                merged.append(entry)
        return merged


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
        if self.read_only:
            self.memory_dir = self.memory_dir.resolve()
        else:
            self.memory_dir.mkdir(exist_ok=True)
        self.index_file = self.memory_dir / "MEMORY.md"
        self.token_budget = token_budget
        self.compressor = SemanticCompressor(token_budget=token_budget)
        if not self.read_only:
            self._ensure_index()

    def _require_writable(self) -> None:
        if self.read_only:
            raise PermissionError("MemoryStore is read-only")

    def _ensure_index(self):
        self._require_writable()
        if not self.index_file.exists():
            self.index_file.write_text("# Memory Index\n\n", encoding="utf-8")

    def store(self, entry: MemoryEntry) -> str:
        self._require_writable()
        filename = f"{entry.type.value}_{entry.id}.md"
        filepath = self.memory_dir / filename
        body = f"""---
name: {entry.title}
description: {entry.content[:100]}
type: {entry.type.value}
importance: {entry.importance}
token_count: {entry.token_count}
compressed: {entry.compressed}
parent_id: {entry.parent_id or ''}
probe_cleanup_token: {entry.metadata.get('probe_cleanup_token', '')}
---

{entry.content}

**metadata**: {json.dumps(entry.metadata, ensure_ascii=False, indent=2)}
**tags**: {', '.join(entry.tags)}
**created**: {entry.created_at}
**last_accessed**: {entry.last_accessed}
**access_count**: {entry.access_count}
**importance**: {entry.importance:.2f}
"""
        filepath.write_text(body, encoding="utf-8")
        self._update_index(entry, filename)
        return str(filepath)

    def _update_index(self, entry: MemoryEntry, filename: str):
        index_line = f"- [{entry.title}]({filename}) -- {entry.content[:100]}\n"
        self._ensure_index()
        content = self.index_file.read_text(encoding="utf-8")
        if entry.title in content:
            lines = content.split("\n")
            new_lines = []
            for line in lines:
                if entry.title in line and line.startswith("- ["):
                    new_lines.append(index_line.strip())
                else:
                    new_lines.append(line)
            self.index_file.write_text("\n".join(new_lines), encoding="utf-8")
        else:
            with open(self.index_file, "a", encoding="utf-8") as f:
                f.write(index_line)

    def delete_probe(
        self,
        memory_type: MemoryType,
        entry_id: str,
        cleanup_token: str,
    ) -> bool:
        """Delete an integration probe after exact type, title, and token checks."""
        self._require_writable()
        if not isinstance(memory_type, MemoryType):
            return False
        if not entry_id or any(
            character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
            for character in entry_id
        ):
            return False
        if not isinstance(cleanup_token, str) or not cleanup_token:
            return False

        filepath = self.memory_dir / f"{memory_type.value}_{entry_id}.md"
        if not filepath.is_file():
            return False

        content = filepath.read_text(encoding="utf-8")
        parts = content.split("---", 2)
        if len(parts) < 3:
            return False
        metadata = {}
        for line in parts[1].splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                metadata[key.strip()] = value.strip()
        if not metadata.get("name", "").startswith(".test-local-integration-"):
            return False
        stored_token = metadata.get("probe_cleanup_token", "")
        if not stored_token or not hmac.compare_digest(stored_token, cleanup_token):
            return False

        filepath.unlink()

        self._ensure_index()
        lines = self.index_file.read_text(encoding="utf-8").splitlines()
        retained = [
            line
            for line in lines
            if f"({filepath.name})" not in line
        ]
        self.index_file.write_text("\n".join(retained) + "\n", encoding="utf-8")
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
        finally:
            os.close(descriptor)

    @staticmethod
    def _parse_entry(filepath: Path, content: str) -> Optional[MemoryEntry]:
        if not content.startswith("---"):
            return None
        parts = content.split("---", 2)
        if len(parts) < 3:
            return None
        fm = parts[1].strip()
        body = parts[2].strip()
        metadata = {}
        for line in fm.split("\n"):
            if ":" in line:
                key, value = line.split(":", 1)
                metadata[key.strip()] = value.strip()
        return MemoryEntry(
            id=filepath.stem.split("_")[-1],
            type=MemoryType(metadata.get("type", "user")),
            title=metadata.get("name", filepath.stem),
            content=body,
            metadata=metadata,
            created_at=metadata.get("created", ""),
            last_accessed=metadata.get("last_accessed", ""),
            access_count=int(metadata.get("access_count", 0)),
            tags=[],
            importance=float(metadata.get("importance", 0.5)),
            token_count=int(metadata.get("token_count", 0)),
            compressed=metadata.get("compressed", "false").lower() == "true",
            parent_id=metadata.get("parent_id"),
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
            return self._load_legacy(memory_type)
        return self._load_read_only(memory_type, **limits)

    def _load_legacy(self, memory_type: Optional[MemoryType]) -> List[MemoryEntry]:
        entries = []
        for filepath in self.memory_dir.glob("*.md"):
            if filepath.name == "MEMORY.md":
                continue
            content = filepath.read_text(encoding="utf-8")
            entry = self._parse_entry(filepath, content)
            if entry is not None and (memory_type is None or entry.type == memory_type):
                entries.append(entry)
        return entries

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
            except (TypeError, ValueError, OverflowError):
                continue
            if entry is not None and (memory_type is None or entry.type == memory_type):
                entries.append(entry)
        return entries

    def consolidate(self) -> Dict[str, int]:
        """记忆整合 — 合并重复、清理过期、语义压缩"""
        entries = self.load()
        stats = {
            "total": len(entries),
            "merged": 0,
            "pruned": 0,
            "compressed": 0,
            "remaining": 0,
            "tokens_saved": 0,
        }

        # 使用语义压缩器进行基于重要性的压缩
        compressed, compress_stats = self.compressor.compress(entries)
        stats["compressed"] = compress_stats["summarized"]
        stats["pruned"] = compress_stats["pruned"]
        stats["merged"] = compress_stats["merged"]
        stats["tokens_saved"] = compress_stats["tokens_saved"]
        stats["remaining"] = len(compressed)

        # 重写压缩后的记忆
        for entry in compressed:
            self.store(entry)

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
        self._compression_history: List[Dict[str, Any]] = []

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
                id=entry.id, type=entry.type, title=entry.title + " [llm-summary]",
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
            id=entry.id, type=entry.type, title=entry.title + " [summary]",
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
        seen_titles: Dict[str, MemoryEntry] = {}
        merged: List[MemoryEntry] = []
        for entry in entries:
            if entry.title in seen_titles:
                existing = seen_titles[entry.title]
                if entry.access_count > existing.access_count:
                    merged = [e for e in merged if e.id != existing.id]
                    merged.append(entry)
                    seen_titles[entry.title] = entry
            else:
                seen_titles[entry.title] = entry
                merged.append(entry)
        return merged

    def _record(self, entry: MemoryEntry, action: str):
        self._compression_history.append({
            "entry_id": entry.id, "title": entry.title,
            "action": action, "tokens": entry.token_count,
            "timestamp": datetime.now().isoformat(),
        })

    @property
    def compression_history(self) -> List[Dict[str, Any]]:
        return list(self._compression_history)

    def clear_history(self):
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
        with open(sys.argv[2], "r", encoding="utf-8") as f:
            conversation = json.load(f)
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
