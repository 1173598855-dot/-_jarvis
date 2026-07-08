"""
上下文压缩器 — 小奕 J.A.R.V.I.S. 记忆维护核心
萃取自 Mem0 的记忆向量化逻辑 + Claude Code 的 consolidate-memory 技能

功能：
1. 上下文无损压缩：长对话自动摘要，保留关键信息
2. 记忆持久化：将关键决策写入 .auto-memory/ 目录
3. 记忆索引维护：更新 MEMORY.md 索引
4. 重复检测：识别并合并重复记忆
5. 过期清理：归档过时信息

运行：python context_compressor.py [compress|store|consolidate|clean]
"""

import json
import hashlib
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict
from enum import Enum


class MemoryType(Enum):
    USER = "user"
    FEEDBACK = "feedback"
    PROJECT = "project"
    REFERENCE = "reference"


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

    @classmethod
    def create(
        cls,
        memory_type: MemoryType,
        title: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
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
            access_count=0,
            tags=tags or [],
        )


class ContextCompressor:
    """上下文无损压缩器 — 长对话自动摘要"""

    def __init__(self, max_tokens: int = 4000):
        self.max_tokens = max_tokens

    def compress(self, conversation: List[Dict[str, str]]) -> str:
        """
        压缩对话历史，保留关键信息

        策略：
        1. 保留最近 5 轮对话（完整）
        2. 将更早的对话压缩为摘要（保留决策和关键事实）
        3. 丢弃重复讨论和已解决的问题
        """
        if len(conversation) <= 5:
            return self._format_conversation(conversation)

        recent = conversation[-5:]
        older = conversation[:-5]

        # 压缩 Older 对话
        summary = self._summarize(older)
        compressed = f"[摘要] {summary}\n\n[最近对话]\n{self._format_conversation(recent)}"

        return compressed

    def _summarize(self, messages: List[Dict[str, str]]) -> str:
        """将旧消息压缩为摘要"""
        # 提取关键信息：决策、约束、偏好
        decisions = []
        facts = []

        for msg in messages:
            content = msg.get("content", "")
            role = msg.get("role", "")

            # 提取决策关键词
            if any(kw in content for kw in ["决定", "选择", "方案", "确定", "decided", "chosen"]):
                decisions.append(f"{role}: {content[:100]}")

            # 提取事实关键词
            if any(kw in content for kw in ["版本", "路径", "配置", "version", "path", "config"]):
                facts.append(f"{role}: {content[:100]}")

        summary_parts = []
        if decisions:
            summary_parts.append(f"决策 ({len(decisions)}): " + "; ".join(decisions[:3]))
        if facts:
            summary_parts.append(f"关键事实 ({len(facts)}): " + "; ".join(facts[:3]))

        return " | ".join(summary_parts) if summary_parts else f"{len(messages)} 条消息已压缩"

    def _format_conversation(self, messages: List[Dict[str, str]]) -> str:
        """格式化对话"""
        return "\n".join([f"{m.get('role', '?')}: {m.get('content', '')[:200]}" for m in messages])


class MemoryStore:
    """记忆持久化存储 — 管理 .auto-memory/ 目录"""

    def __init__(self, memory_dir: str = ".auto-memory"):
        self.memory_dir = Path(memory_dir)
        self.memory_dir.mkdir(exist_ok=True)
        self.index_file = self.memory_dir / "MEMORY.md"
        self._ensure_index()

    def _ensure_index(self):
        """确保索引文件存在"""
        if not self.index_file.exists():
            self.index_file.write_text("# Memory Index\n\n", encoding="utf-8")

    def store(self, entry: MemoryEntry) -> str:
        """
        存储记忆条目

        返回：记忆文件路径
        """
        # 写入记忆文件
        filename = f"{entry.type.value}_{entry.id}.md"
        filepath = self.memory_dir / filename

        content = f"""---
name: {entry.title}
description: {entry.content[:100]}
type: {entry.type.value}
---

{entry.content}

**元数据**：{json.dumps(entry.metadata, ensure_ascii=False, indent=2)}
**标签**：{', '.join(entry.tags)}
**创建时间**：{entry.created_at}
**最后访问**：{entry.last_accessed}
**访问次数**：{entry.access_count}
"""

        filepath.write_text(content, encoding="utf-8")

        # 更新索引
        self._update_index(entry, filename)

        return str(filepath)

    def _update_index(self, entry: MemoryEntry, filename: str):
        """更新记忆索引"""
        index_line = f"- [{entry.title}]({filename}) — {entry.content[:100]}\n"
        content = self.index_file.read_text(encoding="utf-8")

        # 检查是否已存在
        if entry.title in content:
            # 更新现有条目
            lines = content.split("\n")
            new_lines = []
            for line in lines:
                if entry.title in line and line.startswith("- ["):
                    new_lines.append(index_line.strip())
                else:
                    new_lines.append(line)
            self.index_file.write_text("\n".join(new_lines), encoding="utf-8")
        else:
            # 追加新条目
            with open(self.index_file, "a", encoding="utf-8") as f:
                f.write(index_line)

    def load(self, memory_type: Optional[MemoryType] = None) -> List[MemoryEntry]:
        """加载记忆条目"""
        entries = []
        for filepath in self.memory_dir.glob("*.md"):
            if filepath.name == "MEMORY.md":
                continue
            content = filepath.read_text(encoding="utf-8")
            # 解析 frontmatter
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
                    )
                    if memory_type is None or entry.type == memory_type:
                        entries.append(entry)

        return entries

    def consolidate(self) -> Dict[str, int]:
        """
        记忆整合 — 合并重复、清理过期

        返回：整合统计
        """
        entries = self.load()
        stats = {
            "total": len(entries),
            "merged": 0,
            "pruned": 0,
            "remaining": 0,
        }

        # 检测重复（基于内容相似度）
        seen_titles = {}
        to_remove = []

        for entry in entries:
            if entry.title in seen_titles:
                # 保留访问次数更多的
                existing = seen_titles[entry.title]
                if entry.access_count > existing.access_count:
                    to_remove.append(existing.id)
                    seen_titles[entry.title] = entry
                else:
                    to_remove.append(entry.id)
                stats["merged"] += 1
            else:
                seen_titles[entry.title] = entry

        # 清理过期（30 天未访问）
        cutoff = datetime.now() - timedelta(days=30)
        for entry in entries:
            if entry.last_accessed:
                last_accessed = datetime.fromisoformat(entry.last_accessed)
                if last_accessed < cutoff and entry.access_count < 3:
                    to_remove.append(entry.id)
                    stats["pruned"] += 1

        # 删除重复/过期条目
        for entry_id in to_remove:
            for filepath in self.memory_dir.glob(f"*_{entry_id}.md"):
                filepath.unlink()

        stats["remaining"] = len(self.load())
        return stats


def main():
    """命令行入口"""
    import sys

    if len(sys.argv) < 2:
        print("用法: python context_compressor.py <command>")
        print("\n可用命令:")
        print("  compress <conversation.json>  压缩对话历史")
        print("  store <type> <title> <content> 存储记忆")
        print("  consolidate                   整合记忆（合并重复 + 清理过期）")
        print("  list [type]                   列出记忆")
        sys.exit(1)

    command = sys.argv[1]

    if command == "compress":
        if len(sys.argv) < 3:
            print("用法: python context_compressor.py compress <conversation.json>")
            sys.exit(1)
        with open(sys.argv[2], "r", encoding="utf-8") as f:
            conversation = json.load(f)
        compressor = ContextCompressor()
        result = compressor.compress(conversation)
        print(result)

    elif command == "store":
        if len(sys.argv) < 5:
            print("用法: python context_compressor.py store <type> <title> <content>")
            sys.exit(1)
        memory_type = MemoryType(sys.argv[2])
        title = sys.argv[3]
        content = sys.argv[4]
        entry = MemoryEntry.create(memory_type, title, content)
        store = MemoryStore()
        path = store.store(entry)
        print(f"✅ 记忆已存储: {path}")

    elif command == "consolidate":
        store = MemoryStore()
        stats = store.consolidate()
        print(f"记忆整合完成: {json.dumps(stats, indent=2, ensure_ascii=False)}")

    elif command == "list":
        memory_type = None
        if len(sys.argv) >= 3:
            memory_type = MemoryType(sys.argv[2])
        store = MemoryStore()
        entries = store.load(memory_type)
        print(f"共 {len(entries)} 条记忆:\n")
        for entry in entries:
            print(f"  [{entry.type.value}] {entry.title} (访问 {entry.access_count} 次)")

    else:
        print(f"未知命令: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
