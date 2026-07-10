# agentos — TypeScript 多 Agent 框架（技能封装）

**来源**: [framerslab/agentos](https://github.com/framerslab/agentos)
**⭐ 589 Stars** | **语言**: TypeScript | **许可证**: Apache-2.0 | **更新**: 2026-07-08

---

## 核心能力

- **认知记忆（Cognitive Memory）**：长期记忆 + 向量化检索
- **运行时工具生成（Tool Forging）**：Agent 可动态创建新工具
- **多 Agent 编排**：协作 + 委托模式
- **11 个 LLM 提供商**：Claude / GPT / Gemini / Ollama / DeepSeek 等

## 可萃取能力（适配小奕）

| 能力 | 小奕对应路径 | 集成策略 |
|------|------------|---------|
| 认知记忆引擎 | `src/core/brain/context_compressor.py` | 参考其长期记忆分层设计 |
| 运行时工具生成 | `src/core/kernel/plugin_sdk.py` | 借鉴动态工具注册机制 |
| 多 Agent 委托 | Phase 11 待开发 | 解构其 delegation 模式 |
| LLM 提供商抽象 | `src/core/kernel/ollama_manager.py` | 扩展多提供商支持 |

## 集成优先级

**P2** — 远期参考， cognitve memory 设计值得在 Phase 11 深入研究。

## 安全评估

- Apache-2.0 许可证 ✅
- 代码量 25,939 KB，完整审计需分批进行
- 工具生成机制需重点审查（动态代码执行风险）

## 下一步

1. Phase 11 启动前，获取其 `memory/` 目录核心实现
2. 重点关注认知记忆的分层结构（短期/长期/语义）
3. 与 mem0 进行对比，选择更适合小奕混合记忆系统的方案

---

**部署时间**: 2026-07-09 (Iter #16)
**状态**: ✅ 已记录（情报层），⏸ 待 Phase 11 深入研究
