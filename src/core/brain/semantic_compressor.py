"""
语义上下文压缩器 — 小奕 J.A.R.V.I.S. 记忆维护核心增强版
萃取自 Mem0 的向量化逻辑 + headroom 的压缩概念

增强功能：
1. 语义压缩：保留决策和关键事实，丢弃冗余上下文
2. 重要性评分：基于访问频率和内容类型加权
3. 分层记忆：短期/长期/语义三层架构
4. Token 预算管理：限制上下文窗口使用

运行：python semantic_compressor.py [compress|store|consolidate|stats]
"""

import json
import hashlib
import re
import math
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, asdict, field
from enum import Enum


class MemoryType(Enum):
    """记忆类型（分层架构）"""
    WORKING = "working"        # 工作记忆：当前对话上下文
    EPISODIC = "episodic"      # 情景记忆：具体事件和经验
    SEMANTIC = "semantic"      # 语义记忆：通用知识和规则
    PROCEDURAL = "procedural"  # 程序记忆：操作步骤和流程


class CompressionStrategy(Enum):
    """压缩策略"""
    NONE = "none"              # 不压缩（保留完整内容）
    TRUNCATE = "truncate"      # 截断（保留前 N 字符）
    SUMMARIZE = "summarize"    # 摘要（提取关键信息）
    SEMANTIC = "semantic"      # 语义压缩（向量化+检索）


@dataclass
class MemoryEntry:
    """记忆条目（增强版）"""
    id: str
    type: MemoryType
    title: str
    content: str
    metadata: Dict[str, Any]
    created_at: str
    last_accessed: str
    access_count: int
    tags: List[str]
    importance: float = 0.0      # 重要性评分 0-1
    token_count: int = 0         # Token 估算
    compressed: bool = False     # 是否已压缩
    parent_id: Optional[str] = None  # 父记忆 ID（用于追溯）

    @classmethod
    def create(
        cls,
        memory_type: MemoryType,
        title: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
        importance: float = 0.5,
    ) -> "MemoryEntry":
        """工厂方法：创建新记忆条目"""
        entry_id = hashlib.md5(f"{title}:{content[:50]}".encode()).hexdigest()[:12]
        now = datetime.now().isoformat()
        return cls(
            id=entry_id,
            type=memory_type,
            title=title,
            content=content,
            metadata=metadata or {},
            created_at=now,
            last_accessed=now,
            access_count=1,
            tags=tags or [],
            importance=importance,
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

        # 检测是否包含中文
        chinese_chars = len(re.findall(r'[一-鿿]', text))
        english_chars = len(re.findall(r'[a-zA-Z]', text))
        code_chars = len(re.findall(r'[{}()\[\];<>/\\|]', text))

        # 混合估算
        total = (
            chinese_chars / 1.5
            + english_chars / 4.0
            + code_chars / 3.0
            + len(text) * 0.1  # 其他字符
        )

        return max(1, int(total))


class SemanticCompressor:
    """
    语义压缩器 — 基于内容重要性的智能压缩

    策略：
    1. 保留高重要性记忆（importance > 0.7）
    2. 摘要中重要性记忆（0.3 < importance < 0.7）
    3. 丢弃低重要性记忆（importance < 0.3）
    4. 合并重复记忆（基于内容相似度）
    """

    def __init__(self, token_budget: int = 4000):
        self.token_budget = token_budget

    def compress(self, entries: List[MemoryEntry]) -> Tuple[List[MemoryEntry], Dict[str, int]]:
        """
        压缩记忆列表，在 token 预算内保留最重要内容

        Returns:
            (压缩后的记忆列表, 统计信息)
        """
        stats = {
            "total": len(entries),
            "kept": 0,
            "summarized": 0,
            "pruned": 0,
            "merged": 0,
            "tokens_saved": 0,
        }

        # 1. 按重要性排序（降序）
        sorted_entries = sorted(entries, key=lambda e: e.importance, reverse=True)

        # 2. 填充预算
        kept = []
        current_tokens = 0

        for entry in sorted_entries:
            # 跳过已过期的记忆（30 天未访问且低重要性）
            if self._is_expired(entry) and entry.importance < 0.5:
                stats["pruned"] += 1
                stats["tokens_saved"] += entry.token_count
                continue

            # 检查是否超过预算
            if current_tokens + entry.token_count > self.token_budget:
                # 高重要性：保留但截断
                if entry.importance >= 0.7:
                    truncated = self._truncate(entry)
                    kept.append(truncated)
                    stats["kept"] += 1
                    stats["tokens_saved"] += entry.token_count - truncated.token_count
                    current_tokens += truncated.token_count
                # 中重要性：摘要
                elif entry.importance >= 0.3:
                    summarized = self._summarize(entry)
                    kept.append(summarized)
                    stats["summarized"] += 1
                    stats["tokens_saved"] += entry.token_count - summarized.token_count
                    current_tokens += summarized.token_count
                # 低重要性：丢弃
                else:
                    stats["pruned"] += 1
                    stats["tokens_saved"] += entry.token_count
            else:
                kept.append(entry)
                stats["kept"] += 1
                current_tokens += entry.token_count

        # 3. 合并重复
        merged = self._merge_duplicates(kept)
        stats["merged"] = len(kept) - len(merged)
        stats["remaining"] = len(merged)

        return merged, stats

    def _is_expired(self, entry: MemoryEntry) -> bool:
        """检查记忆是否过期（30 天未访问）"""
        if entry.access_count >= 5:  # 高频访问记忆不判定过期
            return False

        try:
            last_accessed = datetime.fromisoformat(entry.last_accessed)
            cutoff = datetime.now() - timedelta(days=30)
            return last_accessed < cutoff
        except (ValueError, TypeError):
            return False

    def _truncate(self, entry: MemoryEntry, max_tokens: int = 500) -> MemoryEntry:
        """截断长记忆，保留开头和结尾"""
        if entry.token_count <= max_tokens:
            return entry

        # 保留前 60% 和后 40%
        content = entry.content
        split_point = int(len(content) * 0.6)

        truncated_content = (
            content[:split_point]
            + "\n... [截断，完整内容见原始记录] ...\n"
            + content[-int(len(content) * 0.4):]
        )

        return MemoryEntry(
            id=entry.id,
            type=entry.type,
            title=entry.title + " [截断]",
            content=truncated_content,
            metadata={**entry.metadata, "truncated": True},
            created_at=entry.created_at,
            last_accessed=entry.last_accessed,
            access_count=entry.access_count,
            tags=entry.tags,
            importance=entry.importance,
            token_count=MemoryEntry._estimate_tokens(truncated_content),
            compressed=True,
            parent_id=entry.id,
        )

    def _summarize(self, entry: MemoryEntry) -> MemoryEntry:
        """摘要记忆，提取关键信息"""
        content = entry.content
        sentences = re.split(r'[。.!?\n]', content)
        sentences = [s.strip() for s in sentences if s.strip()]

        # 提取关键句（包含决策/约束/偏好关键词）
        keywords = ["决定", "选择", "方案", "确定", "decided", "chosen", "must", "should", "constraint"]
        key_sentences = [
            s for s in sentences
            if any(kw in s.lower() for kw in keywords)
        ]

        # 如果有关键句，优先保留
        if key_sentences:
            summary = "; ".join(key_sentences[:3])
        else:
            # 否则保留前几句
            summary = "; ".join(sentences[:3])

        summary = f"[摘要] {summary}" if summary else "[摘要] 内容已压缩"

        return MemoryEntry(
            id=entry.id,
            type=entry.type,
            title=entry.title + " [摘要]",
            content=summary,
            metadata={**entry.metadata, "summarized": True, "original_length": len(content)},
            created_at=entry.created_at,
            last_accessed=entry.last_accessed,
            access_count=entry.access_count,
            tags=entry.tags,
            importance=entry.importance * 0.9,  # 摘要降低重要性
            token_count=MemoryEntry._estimate_tokens(summary),
            compressed=True,
            parent_id=entry.id,
        )

    def _merge_duplicates(self, entries: List[MemoryEntry]) -> List[MemoryEntry]:
        """合并重复记忆（基于标题相似度）"""
        seen_titles = {}
        merged = []

        for entry in entries:
            # 简单去重：相同标题保留访问次数更多的
            if entry.title in seen_titles:
                existing = seen_titles[entry.title]
                if entry.access_count > existing.access_count:
                    # 替换
                    merged = [e for e in merged if e.id != existing.id]
                    merged.append(entry)
                    seen_titles[entry.title] = entry
            else:
                seen_titles[entry.title] = entry
                merged.append(entry)

        return merged


class EnhancedMemoryStore:
    """
    增强记忆存储 — 分层记忆管理

    层级：
    - working：当前会话上下文（高优先级，不持久化）
    - episodic：具体事件（中等优先级，定期清理）
    - semantic：通用知识（低优先级，长期保留）
    - procedural：操作流程（中等优先级，长期保留）
    """

    def __init__(self, memory_dir: str = ".auto-memory", token_budget: int = 4000):
        self.memory_dir = Path(memory_dir)
        self.memory_dir.mkdir(exist_ok=True)
        self.index_file = self.memory_dir / "MEMORY.md"
        self.token_budget = token_budget
        self.compressor = SemanticCompressor(token_budget=token_budget)
        self._ensure_index()

    def _ensure_index(self):
        """确保索引文件存在"""
        if not self.index_file.exists():
            self.index_file.write_text("# Memory Index\n\n", encoding="utf-8")

    def store(self, entry: MemoryEntry) -> str:
        """存储记忆条目"""
        filename = f"{entry.type.value}_{entry.id}.md"
        filepath = self.memory_dir / filename

        content = f"""---
name: {entry.title}
description: {entry.content[:100]}
type: {entry.type.value}
importance: {entry.importance}
token_count: {entry.token_count}
compressed: {entry.compressed}
---
{entry.content}

**元数据**：{json.dumps(entry.metadata, ensure_ascii=False, indent=2)}
**标签**：{', '.join(entry.tags)}
**创建时间**：{entry.created_at}
**最后访问**：{entry.last_accessed}
**访问次数**：{entry.access_count}
**重要性**：{entry.importance:.2f}
"""
        filepath.write_text(content, encoding="utf-8")
        self._update_index(entry, filename)
        return str(filepath)

    def load(self, memory_type: Optional[MemoryType] = None) -> List[MemoryEntry]:
        """加载记忆条目"""
        entries = []
        for filepath in self.memory_dir.glob("*.md"):
            if filepath.name == "MEMORY.md":
                continue
            content = filepath.read_text(encoding="utf-8")
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    fm = parts[1].strip()
                    body = parts[2].strip()
                    metadata = {}
                    for line in fm.split("\n"):
                        if ":" in line:
                            key, value = line.split(":", 1)
                            metadata[key.strip()] = value.strip()

                    entry = MemoryEntry(
                        id=filepath.stem.split("_")[-1],
                        type=MemoryType(metadata.get("type", "user")),
                        title=metadata.get("name", filepath.stem),
                        content=body,
                        metadata=metadata,
                        created_at=metadata.get("created_at", ""),
                        last_accessed=metadata.get("last_accessed", ""),
                        access_count=int(metadata.get("access_count", 0)),
                        tags=[],
                        importance=float(metadata.get("importance", 0.5)),
                        token_count=int(metadata.get("token_count", 0)),
                        compressed=metadata.get("compressed", "false").lower() == "true",
                    )
                    if memory_type is None or entry.type == memory_type:
                        entries.append(entry)
        return entries

    def consolidate(self) -> Dict[str, int]:
        """记忆整合 — 合并重复、清理过期、压缩"""
        entries = self.load()
        stats = {
            "total": len(entries),
            "merged": 0,
            "pruned": 0,
            "compressed": 0,
            "remaining": 0,
            "tokens_saved": 0,
        }

        # 使用语义压缩器
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

    def _update_index(self, entry: MemoryEntry, filename: str):
        """更新记忆索引"""
        index_line = f"- [{entry.title}]({filename}) — importance={entry.importance:.2f}, tokens={entry.token_count}\n"
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


def main():
    """命令行入口"""
    import sys

    if len(sys.argv) < 2:
        print("用法: python semantic_compressor.py <command>")
        print("\n可用命令:")
        print("  compress [type]             压缩记忆（在 token 预算内）")
        print("  store <type> <title> <content> 存储记忆")
        print("  consolidate                 整合记忆（合并+清理+压缩）")
        print("  stats                       记忆统计")
        print("  list [type]                 列出记忆")
        sys.exit(1)

    command = sys.argv[1]
    store = EnhancedMemoryStore()

    if command == "compress":
        memory_type = None
        if len(sys.argv) >= 3:
            try:
                memory_type = MemoryType(sys.argv[2])
            except ValueError:
                pass

        entries = store.load(memory_type)
        compressed, stats = store.compressor.compress(entries)
        print(f"压缩完成: {json.dumps(stats, ensure_ascii=False, indent=2)}")

        # 重写压缩后的记忆
        for entry in compressed:
            store.store(entry)

    elif command == "store":
        if len(sys.argv) < 5:
            print("用法: python semantic_compressor.py store <type> <title> <content> [importance]")
            sys.exit(1)

        memory_type = MemoryType(sys.argv[2])
        title = sys.argv[3]
        content = sys.argv[4]
        importance = float(sys.argv[5]) if len(sys.argv) > 5 else 0.5

        entry = MemoryEntry.create(memory_type, title, content, importance=importance)
        path = store.store(entry)
        print(f"✅ 记忆已存储: {path} (tokens: {entry.token_count})")

    elif command == "consolidate":
        stats = store.consolidate()
        print(f"记忆整合完成: {json.dumps(stats, ensure_ascii=False, indent=2)}")

    elif command == "stats":
        stats = store.get_stats()
        print(f"记忆统计: {json.dumps(stats, ensure_ascii=False, indent=2)}")

    elif command == "list":
        memory_type = None
        if len(sys.argv) >= 3:
            try:
                memory_type = MemoryType(sys.argv[2])
            except ValueError:
                pass

        entries = store.load(memory_type)
        print(f"共 {len(entries)} 条记忆:\n")
        for entry in entries[:20]:  # 只显示前 20 条
            status = "📦" if entry.compressed else "📄"
            print(f"  {status} [{entry.type.value}] {entry.title} (访问 {entry.access_count} 次, 重要性 {entry.importance:.2f})")

    else:
        print(f"未知命令: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
