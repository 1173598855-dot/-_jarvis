# GitHub 技术情报摘要

**更新时间**：2026-09-07

## 编排器契约完整性（Iteration 124）

The repository-owned OpenAPI 3.1 contract advanced to `1.10.0` without a new
runtime dependency. It now records request defaults, bounded timeout and
priority values, non-blank Unicode text, invalid JSON, oversized dispatch
bodies, and complete `AgentResult` evidence across HTTPServer, FastAPI, and
Express. External contract generators remain candidates only when generated
negative testing becomes a measured requirement.

本轮复查了 CrewAI、OpenAI Agents SDK 和 Pydantic AI 的公开仓库元数据；三者均满足活跃度与许可证参考门槛，但当前实现无需新增运行时依赖。项目继续采用标准库 Orchestrator、FastAPI/HTTPServer 适配器、Express Core 代理和确定性 loopback harness。

本轮重点不是引入框架，而是修复契约证据：FastAPI history 上限、HTTPServer dispatch 参数、OpenAPI `maximum` 语义，以及三端真实 dispatch 响应字段。角色专属路由仍不进入共享契约，直到三端拥有统一状态码和 payload 语义。

本报告只保留仍影响当前架构和后续工作的外部技术决策。逐轮搜索流水、损坏编码文本和已经失效的星标统计不再保留。

## Subprocess output decoding on Windows (Iteration 247)

**Sources**: [CPython #105312](https://github.com/python/cpython/issues/105312),
[pytest #7623](https://github.com/pytest-dev/pytest/issues/7623), and
[pytest #14963](https://github.com/pytest-dev/pytest/pull/14963)

Windows subprocess text decoding can select a parent locale or console code
page that differs from the child's encoding. CPython and pytest reports show
that the resulting reader-thread `UnicodeDecodeError` can lose captured output;
pytest's use of `backslashreplace` also demonstrates how undecodable bytes can
remain inspectable.

Current decision: the controlled discovery end-to-end fixture declares UTF-8
at its parent `subprocess.run()` boundary and uses `backslashreplace`. This
preserves valid Unicode and stable byte evidence without changing production
runner behavior, global environment defaults or project dependencies.

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

## OpenAPI 契约验证（Iteration 95）

围绕 Python/Node 跨实现契约测试执行了三类 GitHub 检索。返回候选项目均未达到项目协议要求的采用门槛（>100 Stars、许可合规、近期维护），其中一类检索无结果。

当前决策：

- 不增加 Pact 或第三方 OpenAPI validator 依赖。
- 使用 OpenAPI 3.1 JSON 作为机器可读单一契约。
- 使用标准库 HTTP 客户端真实启动三套服务并验证稳定响应，减少供应链与跨语言工具复杂度。
- 当契约覆盖需要完整 JSON Schema 关键字或消费者驱动契约时，再重新评估成熟验证器。

## 标准错误响应（Iteration 96）

围绕 Problem Details、RFC 9457、Express 与 OpenAPI 错误 envelope 执行了三类检索。两类没有返回候选，另一类结果均为 0 Stars，未达到采用门槛。

当前决策：

- 延续项目已有的 `{ error: { code, message, details? } }` 客户端契约。
- 在 OpenAPI 中维护统一 `ErrorResponse`，不引入 RFC 9457 运行时依赖。
- 错误码保持机器稳定，消息允许按服务本地化。

## Token 用量遥测（Iteration 97）

对 Ollama Token monitor、LLM usage telemetry 和 session usage API 进行了检索。可访问结果最高 7 Stars，部分候选无明确许可证；另外两次请求受 Windows TLS 凭据限制，均未形成可采用组件。

当前决策：

- 不引入新的遥测依赖，复用 Express 已验证的会话快照模型。
- Python 保留兼容的扁平累计 getter，API 层统一输出最新值、累计值、最多 60 个样本和会话开始时间。
- 首阶段数据只存在于当前服务会话，服务重启后清零。

## 本机集成 Profile（Iteration 98）

对 Ollama SSE integration、local integration profile 和 multi-service smoke test 执行三次检索，均受本机 Schannel 凭据错误影响而未获得可评估结果。

当前决策：

- 使用 Python 标准库构建只访问 loopback/显式本机 URL 的可选 profile。
- 默认允许服务缺失时跳过；准备好的环境使用严格开关保证真实链路必须运行。
- 任何已响应服务的 HTTP、JSON、SSE 或业务契约错误都视为失败，不降级为跳过。

## Ollama API 契约（Iteration 99）

Ollama API contract test 检索再次受同一 Schannel 凭据条件阻断。本轮没有外部依赖缺口：现有 `OllamaManager`、Express adapter 和标准库 HTTP fixture 足以验证协议。

当前决策：

- 使用最小本地 Ollama fixture 驱动三套服务的真实 adapter，不复制上游代码。
- 共享契约覆盖 runtime status、model list、Token snapshot、health、system stats 和标准错误。
- 对协议字段执行类型检查，避免 Python truthy 表达式把数组泄漏到布尔字段。

## 只读能力契约（Iteration 101）

本轮 GitHub REST API 评估已成功完成，候选项目均未归档，并满足项目的采用门槛：

| 候选 | GitHub 证据（2026-07-12） | 许可证 | 适用方向 |
|---|---|---|---|
| [Schemathesis](https://github.com/schemathesis/schemathesis) | 3,451 Stars；最近推送 2026-07-11 | MIT | 基于 OpenAPI 的生成式 API 测试 |
| [openapi-core](https://github.com/python-openapi/openapi-core) | 368 Stars；最近推送 2026-06-29 | BSD-3-Clause | Python 请求与响应契约校验 |
| [Ajv](https://github.com/ajv-validator/ajv) | 14,764 Stars；最近推送 2026-05-12 | MIT | Node.js JSON Schema 校验 |

当前决策：

- 本轮不增加依赖。现有 `_assert_json_shape` 与真实三服务 harness 已覆盖插件、记忆和事件的稳定只读响应。
- 保持 OpenAPI 3.1 JSON 为单一契约，避免为同一响应在 Python 与 Node 引入两套校验依赖。
- 当项目需要生成式负例、完整 JSON Schema 关键字或独立消费者契约时，再优先复评 Schemathesis 与 openapi-core；Ajv 保留为 Node 独立校验候选。

## 错误响应与流式契约（Iterations 102-106）

本轮通过 GitHub REST API 复查了错误响应与 SSE 契约候选：

| 候选 | 2026-07-12 证据 | 许可证 | 当前决策 |
|---|---|---|---|
| [Schemathesis](https://github.com/schemathesis/schemathesis) | 3,451 Stars；2026-07-08 发布 `v4.22.4`；含 SSE 指南 | MIT | 保留为 P1 生成式错误/SSE 测试候选 |
| [Spectral](https://github.com/stoplightio/spectral) | 3,151 Stars；2026-06-30 发布 `6.16.1` | Apache-2.0 | 保留为 P1 静态 OpenAPI lint 候选 |
| [Prism](https://github.com/stoplightio/prism) | 4,983 Stars；2026-07-10 有提交 | Apache-2.0 | 保留为 P1.5 Express 测试代理候选 |
| [Pact JS / Python](https://github.com/pact-foundation/pact-js) | JS 1,789 Stars；Python 677 Stars；均近期维护 | MIT | 延后到 P2，避免 FFI 与跨语言工件复杂度 |

当前决策：不新增依赖。确定性真实三服务 harness 已捕获并回归了
`INVALID_JSON`、`INVALID_REQUEST`、`MISSING_COMMAND`、`MISSING_PLUGIN_ID`
与 `PLUGIN_NOT_FOUND`；尚未需要生成式负例、完整 JSON Schema 关键字或重连语义。
当 SSE 进入共享帧 schema 或错误路径扩展到更多写操作时，优先复评 Schemathesis
与 Spectral，并把任何 fuzzing 限制在隔离 loopback fixture。

## 本地终端能力边界（Iterations 107-111）

本轮复查的高质量候选均只作为架构参考，不引入运行时依赖：

| 候选 | 证据 | 采纳决策 |
|---|---|---|
| [Tauri](https://github.com/tauri-apps/tauri) | 108,955 Stars，Apache-2.0，2026-07-11 有提交 | 借鉴 capabilities 的默认拒绝模型，不引入 Rust 桌面运行时 |
| [Cline](https://github.com/cline/cline) | 64,558 Stars，Apache-2.0，2026-07-11 发布 | 借鉴显式审批与审计思路，不引入编辑器/CLI 生态 |
| [Pydantic AI](https://github.com/pydantic/pydantic-ai) | 18,435 Stars，MIT，2026-07-11 发布 | 借鉴工具边界审批模型，不引入新 Python 框架 |
| [OWASP Cheat Sheet Series](https://github.com/OWASP/CheatSheetSeries) | 32,562 Stars，CC-BY-SA-4.0，2026-07-09 有提交 | 仅作 REST、Agent 与命令注入防护规范参考 |

当前决策：以项目内最小 capability boundary 落地默认拒绝、精确 origin allowlist、常量时间令牌比较和固定诊断操作；不引入外部依赖或复制上游代码。

## 规范 SSE 契约（Iteration 112）

本轮通过 GitHub REST API 复查了流式契约候选的维护状态：

| 候选 | 2026-07-12 证据 | 许可证 | 当前决策 |
|---|---|---|---|
| [Schemathesis](https://github.com/schemathesis/schemathesis) | 3,452 Stars；2026-07-12 有推送；未归档 | MIT | 保留为后续隔离环境中的生成式 SSE/错误测试候选 |
| [Spectral](https://github.com/stoplightio/spectral) | 3,151 Stars；2026-07-02 有推送；未归档 | Apache-2.0 | 保留为后续 OpenAPI lint 候选 |

当前决策：不新增依赖。以 OpenAPI `1.4.0` 的事件帧 schema、loopback Ollama fixture 和真实三服务回归验证规范内容帧、嵌套错误帧与终止语义；生成式输入和静态 lint 有明确需求时再复评候选。

## Express Git 错误契约（Iteration 113）

本轮通过 GitHub REST API 复查了错误处理和契约测试候选：

| 候选 | 2026-07-12 证据 | 许可证 | 当前决策 |
|---|---|---|---|
| [http-errors](https://github.com/jshttp/http-errors) | 1,558 Stars；2026-06-01 有推送；未归档 | MIT | 不引入；现有 `sendApiError` 已满足本轮边界 |
| [zalando/problem](https://github.com/zalando/problem) | 950 Stars；2026-06-30 有推送；未归档 | MIT | 不引入；RFC 风格迁移超出当前兼容范围 |
| [Schemathesis](https://github.com/schemathesis/schemathesis) | 3,452 Stars；2026-07-12 有推送；未归档 | MIT | 保留为后续生成式错误路径测试候选 |

当前决策：复用既有 ErrorResponse 和真实 Node 子进程回归，不新增依赖。`JARVIS_GIT_COMMAND` 仅是受信任进程环境的诊断/部署配置，绝不来自 HTTP 输入。

## POST SSE 共享契约（Iteration 114）

本轮通过 GitHub REST API 复查 OpenAPI/SSE 契约候选：

| 候选 | 2026-07-12 证据 | 许可证 | 当前决策 |
|---|---|---|---|
| [Schemathesis](https://github.com/schemathesis/schemathesis) | 3,452 Stars；2026-07-12 有推送；未归档 | MIT | 保留为后续隔离生成式 API/SSE 测试候选 |
| [Spectral](https://github.com/stoplightio/spectral) | 3,151 Stars；2026-07-02 有推送；未归档 | Apache-2.0 | 保留为后续静态 OpenAPI lint 候选 |
| [Prism](https://github.com/stoplightio/prism) | 4,983 Stars；2026-07-10 有推送；未归档 | Apache-2.0 | 保留为后续 mock/代理契约候选 |
| [OpenAPI Specification](https://github.com/OAI/OpenAPI-Specification) | 31,085 Stars；2026-07-10 有推送；未归档 | Apache-2.0 | 继续作为 OpenAPI 3.1 语义参考 |

当前决策：不新增依赖。使用共享 OpenAPI `1.5.0` 和 loopback Ollama fixture 验证 GET/POST SSE 等价路径、规范帧、终止标记和 `INVALID_REQUEST`，避免为单一路径引入独立运行时或测试代理。

## 请求体边界（Iteration 115）

本轮通过 GitHub REST API 复查与 Python ASGI 请求边界直接相关的维护项目：

| 候选 | 2026-07-12 证据 | 许可证 | 当前决策 |
|---|---|---|---|
| [FastAPI](https://github.com/fastapi/fastapi) | 100,404 Stars；2026-07-10 有推送；未归档 | MIT | 保持现有 Pydantic/ASGI 集成，不增加新框架 |
| [Starlette](https://github.com/Kludex/starlette) | 12,470 Stars；2026-07-04 有推送；未归档 | BSD-3-Clause | 复用现有 ASGI middleware 扩展点，不增加 body-limit 依赖 |

当前决策：不新增依赖。以跨服务 32 KiB `Content-Length` 边界、OpenAPI `1.6.0` 和 loopback oversized JSON 回归锁定第一层请求体防护；后续再处理 chunked/unknown-length body 的流式计数。

## 分块 ASGI 请求边界（Iteration 116）

本轮通过 GitHub REST API 复查处理 ASGI/HTTP 数据流的候选：

| 候选 | 2026-07-12 证据 | 许可证 | 当前决策 |
|---|---|---|---|
| [Uvicorn](https://github.com/Kludex/uvicorn) | 10,825 Stars；2026-07-09 有推送；未归档 | BSD-3-Clause | 复用 ASGI `receive` 语义，不增加服务器运行时依赖 |
| [h11](https://github.com/python-hyper/h11) | 560 Stars；2025-04-24 有推送；未归档 | MIT | 保留为 HTTP 流语义参考，不直接调用内部解析器 |

当前决策：不新增依赖。中间件在可移植 ASGI `receive` 边界累计字节，并以单元测试验证 32 KiB-plus 分块在下游读取前变为 413，不耦合 Uvicorn/h11 内部实现。
## 确定性本机集成门禁（Iteration 122）

本轮复查确认不需要引入新的运行时依赖。新增的 `local_ollama_fixture.py` 只实现 profile 所需的四类 Ollama HTTP 行为；`ci_local_integration.py` 通过动态 loopback 端口启动 FastAPI、Express 和 fixture，复用现有 `local_integration_profile.py --require-services`，并在 Windows/POSIX 上关闭父进程日志句柄后清理临时目录。GitHub Actions 现在可以在没有外部 Ollama daemon 或模型下载的情况下执行强制服务门禁，真实服务 profile 仍保留给准备好的本地 Ollama 环境。

## 进程隔离终端与代理错误契约（Iteration 121）

本轮复查确认不需要新增运行时依赖：HTTP 服务默认终端能力改由本地 `TerminalWorker` 进程边界承载，子进程使用最小环境、专用临时目录和固定只读操作；POSIX 环境可通过受信任的 UID/GID 配置进一步降权。共享 OpenAPI 升级到 1.8.0，使用 Express-only `x-jarvis-api-fallback` 描述 `API_NOT_FOUND`，并为 Ollama 状态/模型、系统遥测和 Core API 代理错误引用 `ErrorResponse`。三端未对等实现的 orchestrator/role 路径不纳入共享契约。

## 共享编排器路由契约（Iteration 123）

本轮继续不新增运行时依赖。共享 OpenAPI 升级到 1.9.0，覆盖三端均已提供的 orchestrator agents、history 和 dispatch 路径；真实 harness 同时验证 Python HTTPServer、FastAPI 与 Express Core 代理的成功 schema、history 上限和稳定错误 envelope。role 专属路由仍保持显式范围，不因单端实现而扩张共享契约。

## 生产角色执行（Iteration 126）

三组定向 GitHub 检索覆盖多 Agent 角色执行、本地 Ollama Agent 框架和 Agent 执行策略。两组查询没有返回合格候选；本地 Ollama 查询找到 `kstevica/captain-claw`（161 Stars、MIT、2026-07-14 活跃）以及一个不符合项目部署许可规则的 AGPL 候选。

当前决策：不新增依赖。仓库已经具备 Ollama client、角色注册表、编排器、确定性 fixture 和三端真实契约 harness；引入完整框架会重复这些边界。Iteration 126 复用现有 `AgentFactory` 注入点完成真实模型执行，同时保持角色工具默认无执行权限。

## 角色错误恢复（Iteration 127）

三组 GitHub 检索覆盖 Agent orchestrator retry state、multi-agent failure recovery 和 task retry/backoff；直接结果最高仅 2 Stars，未达到采用门槛。高质量参考项目的当前元数据为 Microsoft AutoGen 59,730 Stars（CC-BY-4.0）、Pydantic AI 18,521 Stars（MIT）和 LangGraph 37,295 Stars（MIT），均在 2026-07-14 活跃。

当前决策：不新增依赖。缺陷来自项目内 `_RegisteredAgent` 把已结束 handler 错误和仍可能运行的 timeout 合并为同一内部状态。Iteration 127 增加内部 recoverable 标记与显式恢复边界，普通错误可为下一请求恢复，timeout 继续默认拒绝，避免隐藏重试或重叠执行。

## 角色工具授权边界（Iteration 128）

三组 GitHub 检索覆盖 AI Agent 工具权限策略、LLM capability sandbox 和进程隔离 Agent worker。检索发现 [Kontext CLI](https://github.com/kontext-security/kontext-cli)（210 Stars、MIT、2026-07-14 推送）与 [Doberman Core](https://github.com/fu351/Doberman-Core)（112 Stars、Apache-2.0、2026-07-12 推送）满足采用门槛。

当前决策：不新增依赖。Kontext 的 Go daemon、macOS 自助安装、local judge 与托管事件流，以及 Doberman 的完整 MCP proxy、认证、策略、存储和 TUI，均显著大于当前 Python 角色边界。Iteration 128 借鉴两者“策略必须位于真实执行路径”和“异常默认拒绝”的原则，落地项目内 `RoleToolPolicy`/`RoleToolBroker`、精确三重授权与有界审计。

### 本轮需求分析（Bridge Analysis）

| 优先级 | 需求描述 | 对应技能/证据 | 调用时机 | 状态 |
|---|---|---|---|---|
| P0 | 防止 profile 工具声明变成环境权限 | TDD + Python secure-by-default review | broker 与提示接入前 | 已完成 |
| P1 | 执行已授权的只读角色工具 | 现有 `TerminalWorker` capability | broker 边界完成后 | 待后续迭代 |
| P1 | 终止超时的角色工作 | 现有进程 worker 模式 | 角色执行隔离设计前 | 待后续迭代 |
