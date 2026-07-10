# GitHub 技术情报摘要

**更新时间**：2026-07-10

本报告只保留仍影响当前架构和后续工作的外部技术决策。逐轮搜索流水、损坏编码文本和已经失效的星标统计不再保留。

## Ollama Streaming Adapter

**来源**：[Ollama API 文档](https://github.com/ollama/ollama/blob/main/docs/api.md)

关键结论：Ollama `/api/chat` 使用 POST，并返回逐行 JSON；浏览器 `EventSource` 需要 SSE 帧。

当前决策：

- 保持 Ollama 上游协议不变。
- 在 `frontend/server.js` 将每行 JSON 转换为 `data: <json>\n\n`。
- 同时支持 GET 与 POST `/api/ollama/chat/stream`，覆盖 EventSource 和 fetch streaming 客户端。
- 使用 `frontend/server.test.js` 的假 Ollama 服务验证适配层。

## CanopyKit

**来源**：[CanopyKit](https://github.com/redkauribrewersyeast417/CanopyKit)

可借鉴能力：多 Agent 协调、任务路由、状态记录和运行时指标。

应用方向：

- Phase 8/11：映射到 `jarvis-orchestrator` 与 Plugin sandbox。
- Phase 12：增加任务完成率、平均耗时和失败率断言。

## LibreChat

**来源**：[LibreChat](https://github.com/danny-avila/LibreChat)

可借鉴能力：多模型切换、MCP/Skills、Code Interpreter 和自托管统一入口。

应用方向：

- Phase 9/10：评估统一聊天与模型切换信息架构。
- Phase 7：参考 Skill/Plugin 注册、发现与权限展示。

## AI Interpreter

**来源**：[AI Interpreter](https://github.com/AntonMinin/ai-interpreter)

可借鉴能力：ASR、机器翻译、TTS 与虚拟音频设备组成的实时流水线。

应用方向：

- Phase 10：实时字幕/翻译 Widget。
- Phase 11：本地多模态感知流水线。
- Phase 5：先由 `environment-probe` 验证音频设备与驱动能力。

## 采纳原则

1. 不直接复制上游实现，优先提取能力契约和测试场景。
2. 新依赖必须通过许可证、供应链和沙箱审计。
3. 只有进入项目路线并能对应本地测试的发现才写入本报告。
4. 失效项目、搜索流水和短期热度数据不进入长期文档。
