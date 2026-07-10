"""
废弃 DEPRECATED — 此文件已合并到 context_compressor.py (2026-07-09)

所有功能已迁移至 context_compressor.py：
- MemoryEntry 增强字段（importance, token_count, compressed, parent_id）
- MemoryEntry._estimate_tokens() 多语言 token 估算
- CompressionStrategy 枚举
- SemanticCompressor 类（重要性评分 + token 预算压缩）
- EnhancedMemoryStore 类（get_stats() 统计）

保留此文件仅为兼容旧 import，不执行任何操作。
"""

# DEPRECATED — 2026-07-09
# All functionality merged into context_compressor.py
