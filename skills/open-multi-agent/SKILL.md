# open-multi-agent — 多子 Agent 编排框架（技能封装）

**来源**: [open-multi-agent/open-multi-agent](https://github.com/open-multi-agent/open-multi-agent)
**⭐ 6,540 Stars** | **语言**: TypeScript | **许可证**: MIT | **更新**: 2026-07-08

---

## 核心能力

- **目标驱动的 Agent 编排**：描述目标后，协调器自动将其分解为 Task DAG
- **多 LLM 支持**：Claude / ChatGPT / Gemini / DeepSeek / Ollama 本地模型
- **任务图执行**：DAG 拓扑排序 + 并行调度
- **TypeScript 原生**：与前端 Solid.js 技术栈一致

## 可萃取能力（适配小奕）

| 能力 | 小奕对应路径 | 集成策略 |
|------|------------|---------|
| Task DAG 分解器 | `src/core/brain/task_planner.py` | 解构其目标→DAG 算法，用 Python 重写 |
| 协调器（Coordinator） | `src/core/brain/orchestrator.py` | 借鉴其 ReAct 规划循环 |
| 多 LLM 适配器 | `src/core/kernel/ollama_manager.py` | 扩展支持 OpenAI/Claude API |
| MCP 工具集成 | `src/core/kernel/plugin_sdk.py` | 已有 plugin_sdk，参考其 MCP 协议 |

## 集成优先级

**P1** — Phase 11（小奕 AI 本格化进化）期间集成，赋能多 Agent 任务编排。

## 安全评估

- MIT 许可证 ✅
- 无高危代码模式（TypeScript 代码库）
- 代码量适中（6,891 KB），可完整审计

## 下一步

1. Phase 11 启动前，调用 `mcp__workspace__web_fetch` 获取其核心 `coordinator.ts` 源码
2. 调用 `security-auditor` 技能进行 AST 审计
3. 解构 Task DAG 算法，重写为 Python `task_planner.py`

---

**部署时间**: 2026-07-09 (Iter #16)
**状态**: ✅ 已记录（情报层），⏸ 待 Phase 11 集成
