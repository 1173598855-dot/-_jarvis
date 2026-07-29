# 小奕 J.A.R.V.I.S. 项目分析

**扫描时间**：2026-07-29

**扫描范围**：`C:\GitHub\贾维斯\`

**依据**：实际文件树、服务入口、配置与 Iteration 138 本轮测试结果

## 结论

项目已从 Widget 聚合页重构为本地优先的六视图指挥中心。Solid.js 前端通过统一 API 客户端、SSE 客户端和共享轮询资源消费 Express；Express 提供真实系统/Git/Ollama 数据，并通过可选 Core API 桥接记忆、插件和事件能力。Python HTTPServer 与 FastAPI 继续作为可替换的核心服务入口。

当前工程重点已转入阶段 D：在既有三服务契约、真实集成门禁和 Worker 安全边界上，建立本地优先的能力注册、解析与安全部署链。Iteration 135-138 已完成版本化记录、只读发现、严格兼容求值、确定性解析、已验证的禁用包暂存和可逆生命周期。包内容不会被导入或执行，网络或 URL 输入不会被接受。

## 当前规模

| 范围 | 盘点结果 |
|---|---:|
| `src/` Python | 37 个文件，12,143 行非空代码/文档行 |
| `src/` TypeScript | 0 个文件 |
| `frontend/src/` | 38 个 TS/TSX 文件，约 4,211 行 |
| `tests/` Python | 58 个 `test_*.py` 文件 |
| 规范 Python 聚合套件 | 500 个用例（498 通过、2 跳过） |
| 完整 Python discovery | 1357 个用例（1355 通过、2 跳过） |
| 前端 Vitest | 129 个用例通过 |
| Playwright | 5 项通过，1 项按桌面条件跳过 |
| 本地 Skill | 19 个 |
| Plugin | 2 个 |
| 滚动审计报告 | 10 份（Iteration 129-138） |

## 运行架构

| 服务 | 默认端口 | 职责 |
|---|---:|---|
| Vite | 5173 | Solid.js 指挥中心开发服务器与 Express 代理 |
| Express | 9999 | Ollama SSE、系统/Token 遥测、Git 数据与 Core API 桥接 |
| Python HTTPServer | 8080 | 标准库兼容 API |
| FastAPI | 8080 | 插件、角色、多代理与完整 Core API |
| Ollama | 11434 | 本地模型运行时 |

Python HTTPServer 与 FastAPI 是替代入口，不能同时监听 8080。Express 在未配置 `JARVIS_CORE_API_URL` 时仍可提供对话、运行监控、模型和仓库视图；记忆与插件控制会如实显示能力不可用。三种服务默认只监听 `127.0.0.1`，未设置 CORS 时仅允许两个本地 Vite origin；需要外部部署时必须显式配置网络边界。

## 前端模块地图

```text
frontend/src/
  App.tsx                         懒加载六个工作视图
  app/
    navigation.ts                导航单一来源
    runtime-resources.tsx        共享轮询资源
  components/
    layout/                      三栏壳层、状态栏、活动栏、移动导航
    ui/                          Kobalte/Lucide 基础组件
  primitives/
    create-polling-resource.ts   加载、过期、失败和刷新状态机
  services/
    jarvis-api.ts                类型化 REST 客户端
    chat-stream.ts               Ollama SSE 客户端
  views/                         对话、运行、仓库、模型、记忆、插件
  styles/                        Token、全局样式和组件样式
  tests/                         Vitest 组件与服务测试

frontend/e2e/
  command-center.spec.ts         桌面/移动浏览器流程与截图
```

## Iteration 93 已解决

- 建立类型化 API 客户端、统一错误格式和可中止 SSE 解析。
- 将系统指标切换为 `systeminformation` 真实数据，并从 Ollama 响应累积 Token 用量。
- 新增 Express 到 Core API 的能力探测与记忆、插件、事件代理。
- 建立共享轮询资源，统一 loading、ready、empty、stale、degraded 和 error 状态。
- 交付六个中文工作视图，以及 Kobalte、Lucide、Chart.js 驱动的可访问 UI 系统。
- 交付固定桌面三栏、状态抽屉和 390px 移动底部导航；断点为 1279px 与 767px。
- 删除旧 Dashboard、Widget 引擎和 `innerHTML` 渲染路径，保留只读 Git 与受能力约束的插件操作。
- 新增 Playwright 确定性 API fixture、六视图导航、流式对话、无溢出断言和桌面/移动截图审查。
- 通过 Lucide 子路径导入与 Vite CommonJS 依赖预构建，消除开发态约 2100 个模块请求及懒加载挂起。

## Iteration 94 已解决

- 将 FastAPI 的 `startup`/`shutdown` 装饰器迁移为异步 lifespan context manager，保留原有资源关闭行为。
- 新增生命周期回归断言，防止弃用的 `@app.on_event` 钩子回归。
- 修复标准库 HTTP 服务的 Ollama 模型列表序列化，使其与 FastAPI 的数据类响应保持一致。

## Iteration 95 已解决

- 新增 `contracts/core-api.openapi.json`，以 OpenAPI 3.1 维护三套服务的稳定响应契约。
- 新增真实跨实现测试，同时启动 Express、Python HTTPServer 和 FastAPI，验证健康与系统遥测响应。
- 为 Express 补齐真实网络接口遥测，并在 provider 不可用时保留明确 degraded 状态。

## Iteration 96 已解决

- 统一三套服务的终端缺参错误 envelope 与稳定错误码 `MISSING_COMMAND`。
- 扩展共享 OpenAPI 契约，覆盖终端请求、400 响应和可复用 `ErrorResponse`。
- FastAPI 显式 HTTP 错误统一经过 exception handler，避免 `detail` 与 `error` 形状漂移。

## Iteration 97 已解决

- 统一三套 `/api/ollama/token-usage` 为会话快照模型，覆盖最新值、累计值、样本和开始时间。
- Python `OllamaManager` 增加最多 60 个内存样本，同时保留原有扁平累计 getter。
- Token 快照进入共享 OpenAPI 和真实三服务契约测试。

## Iteration 98 已解决

- 新增可选本机集成 profile，在真实服务可用时执行 SSE、记忆写读和插件读取。
- 默认模式对缺失服务明确 `SKIPPED`，严格模式将缺失服务作为失败。
- 区分服务不可用与已响应服务的契约失败，避免把真实回归误判为环境跳过。

## Iteration 99 已解决

- 共享 OpenAPI 与真实三服务测试新增 Ollama status/models 覆盖。
- 使用单一本地 Ollama HTTP fixture 驱动 Express 与两个 Python adapter，避免外部服务依赖。
- 修复 Python `gpu_available` 在空列表情况下返回 `[]` 的类型漂移。
- 修复 Windows 下 Playwright 内置 webServer 清理挂起，改由 Node runner 显式管理 Vite 生命周期。

## Iteration 100 已解决

- Token 统计改为直接消费 Ollama 原生计数字段，并覆盖非流式、内部流式和 SSE generator；三套服务契约测试核对真实增量。
- FastAPI 新增隔离 app/state 工厂，测试客户端退出只关闭自己的编排器，不再污染模块级全局状态。
- 本机 profile 只将稳定的 `OLLAMA_UNAVAILABLE` 归类为可选服务不可用，拒绝 502 无效响应及错误或不完整 SSE。
- 记忆探针清理由 memory type、`.test-local-integration-*` 标题和一次性 token 三重约束，普通记忆及同 ID 其他类型不会被删除。
- 契约校验补齐本地引用、联合类型、`const`、下界和严格数字类型；E2E runner 在 headed/headless 模式启动前检查并独占 strict port。

## Iteration 101 已解决

- 共享 OpenAPI 升级到 `1.2.0`，新增插件、记忆与事件只读列表路径及六个可复用 schema。
- 三套服务的真实契约测试覆盖能力响应；Express 通过测试注入的 Core API 地址验证代理结果。
- Express 监听 host 改为 `JARVIS_HOST` 可配置，契约 harness 与 Vitest 均显式绑定 loopback，避免测试服务暴露到所有接口。
- 前端服务测试移除 19997-19999 固定端口，两个 fixture 读取 `server.address().port`，Express 从实际启动地址取得动态端口后再执行 health 轮询。
- 两套 Python 记忆列表序列化补齐 `tags`，与既有前端 `MemoryEntry` 类型保持一致。
- Schemathesis、openapi-core 与 Ajv 均通过 GitHub 许可和维护评估；当前覆盖无需新增依赖。

## Iteration 102-106 已解决

- 跨 Python HTTPServer、FastAPI 与 Express 的真实契约测试新增损坏 JSON、非对象 JSON、缺少终端命令、缺少插件标识和未知插件场景。
- 三端现在统一使用 `ErrorResponse`：`INVALID_JSON`、`INVALID_REQUEST`、`MISSING_COMMAND`、`MISSING_PLUGIN_ID` 与 `PLUGIN_NOT_FOUND` 均有稳定 HTTP 状态和机器错误码。
- OpenAPI 为 `POST /api/plugins/load` 声明了请求体、400 与 404 响应；Express 保持 Core API 代理，因此不复制插件业务逻辑。
- FastAPI 的框架级请求校验经适配器收敛为共享错误 envelope，测试不再依赖 422 `detail` 形状。
- GitHub 复查确认 Schemathesis、Spectral 与 Prism 均合格；当前没有为轻量确定性回归引入额外依赖。
- 静态安全审计识别出既有未鉴权终端执行暴露，已归档到 `RISK_COMPONENTS.log`；该破坏性部署修复保留为独立 P0。

## Iteration 107-111 已解决

- Express 默认绑定改为 loopback，三套服务的 CORS 默认收敛为两个本地 Vite origin；Docker 仅将开发端口发布到宿主机 loopback。
- 新增 `runtime_security`，终端 HTTP API 必须同时启用 `JARVIS_TERMINAL_ENABLED=true` 并配置能力令牌；缺失配置返回 `403 TERMINAL_DISABLED`，错误令牌返回 `401 TERMINAL_UNAUTHORIZED`。
- 新增固定 HTTP 操作策略，只允许受限的 `echo`、`pwd`、`whoami`、`hostname` 和 `date`，并对参数和超时设置边界；解释器、包管理器、下载器和环境读取器在进程创建前被拒绝。
- Express 删除直接 Python 子进程调用，只代理 Core API 并透传能力令牌；同时限制 JSON 请求体为 32 KiB 并移除 `X-Powered-By`。
- OpenAPI 升级至 `1.3.0`，记录令牌请求头和 401/403 envelope；GitHub 复查仅借鉴 Tauri、Cline、Pydantic AI 的能力边界模型，不新增依赖。

## Iteration 112 已解决

- 将 `GET /api/ollama/chat/stream` 纳入 OpenAPI `1.4.0`，声明规范内容帧、错误帧以及成功终止标记。
- Python HTTPServer 现在可按带 query 的流路径路由；三端均输出 `{ model, content, done }`，错误统一为 `OLLAMA_STREAM_ERROR` envelope，且失败流不再发送 `[DONE]`。
- Express 将原生 Ollama NDJSON/SSE 适配为规范帧，保留原生 token 计数；Solid 客户端相应消费 `content`。

## Iteration 113 已解决

- Express Git metadata 端点的子进程启动与退出失败均收敛为 `{ error: { code, message } }`，稳定错误码为 `GIT_COMMAND_FAILED`，不再回显系统可执行文件错误。
- 新增仅进程环境可配置的 `JARVIS_GIT_COMMAND`，默认仍为 `git`；真实 Node 子进程回归验证缺失可执行文件时服务继续存活。

## Iteration 114 已解决

- 共享 OpenAPI 升级至 `1.5.0`，声明浏览器实际使用的 `POST /api/ollama/chat/stream`，包括 JSON body、SSE 成功帧和 400 ErrorResponse。
- Python HTTPServer 与 FastAPI 新增 POST SSE 适配器，并复用各自的规范 SSE 写入路径；GET EventSource 兼容入口保持不变。
- 三端非对象 POST body 一律返回 `400 INVALID_REQUEST`，真实 loopback 契约测试验证同一成功请求的规范帧、唯一 `[DONE]` 和错误 envelope。

## Iteration 115 已解决

- 共享 OpenAPI 升级至 `1.6.0`，为 POST SSE 声明稳定的 `413 REQUEST_BODY_TOO_LARGE` ErrorResponse。
- Python HTTPServer 在读取前、FastAPI 在 ASGI middleware 中、Express 在 JSON parser 错误边界中统一限制声明的 JSON body 为 32 KiB。
- 真实三服务 loopback 回归使用同一 32 KiB-plus body，验证超限请求不会开始 Ollama stream，并一律返回嵌套 413 error envelope。

## Iteration 116 已解决

- FastAPI ASGI middleware 已从 `Content-Length` 检查扩展到 `receive` 字节累计，覆盖 headerless/chunked request bodies。
- 达到 32 KiB 且 `more_body: true` 的序列会在下游读取前直接返回 `413 REQUEST_BODY_TOO_LARGE`，并以 `http.disconnect` 终止应用侧读取。
- ASGI 单元回归覆盖临界分块与重复响应防护，消除上一轮记录的未知长度 body 缺口。

## Iteration 117-119 已解决

- 非流式 Ollama chat 已由共享成功 schema 约束：三端对上游 HTTP、连接、JSON 和语义不完整的响应统一返回 `502 OLLAMA_UPSTREAM_ERROR`；真实三服务 fixture 回归覆盖伪成功 `200`。
- Express 系统遥测为每个 provider 探测增加有界超时。超时只会将关联字段标记为 unavailable 并保持其它真实指标可用。
- 默认内部 `TerminalExecutor` 使用实例专属临时目录和最小环境，拒绝调用者传入的工作目录或环境覆写，并在 FastAPI 与 Python HTTPServer 生命周期结束时清理目录。

## Iteration 120 已解决

- Express 对所有未匹配的 `/api/*` 路由返回稳定的 `404 API_NOT_FOUND` ErrorResponse，不再将 API 请求错误地交给 SPA 页面回退或默认 HTML 错误页。
- 新增 GET/POST 未知 API 路径的真实 Node 集成回归，验证状态码、JSON content type 和嵌套错误结构。
- 为真实系统遥测集成测试设置与 3 秒 provider 探测预算相称的 10 秒测试预算，避免全量 Vitest 并发启动开销造成误报；生产探测超时逻辑不变。

## Iteration 124 已解决

- FastAPI orchestrator history now clamps `limit` to the shared `1..100` range, and OpenAPI documents `maximum: 100`.
- Python HTTPServer orchestrator dispatch now forwards and validates `timeout` and `priority` with the shared defaults and bounds.
- The local contract shape validator enforces numeric `maximum` constraints.
- The live loopback harness dispatches through Python HTTPServer, FastAPI, and Express and validates complete `AgentResult` fields plus invalid dispatch errors.
- Express's deterministic Core fixture now includes `error` and `duration_ms`, closing the false-positive success shape.
- Shared OpenAPI `1.10.0` records the public defaults, `timeout` range `1..300`, non-blank text fields, and dispatch `413` response.
- All three adapters reject the same invalid option/type/surrogate matrix, while the live harness proves explicit `45/3` and default `300/1` task values reach the orchestrator.
- Python HTTPServer converts extreme JSON decoder failures into `400 INVALID_JSON` and uses bounded request draining to preserve stable `413` responses on Windows.

Role-specific routes remain intentionally outside the shared contract because the three adapters still do not expose equivalent behavior.

## Iteration 123 已解决

- 共享 OpenAPI 升级到 `1.9.0`，纳入 `GET /api/orchestrator/agents`、`GET /api/orchestrator/history` 和 `POST /api/orchestrator/dispatch`，并声明 agent、history、dispatch 及代理错误 schema。
- Express 新增三条 Core API 代理路由；Python HTTPServer 与 FastAPI 的 history 查询统一限制为 `1..100`，三端真实 harness 验证响应形状和代理失败 envelope。
- 当前共享 orchestrator 子集已完成；role 专属路由仍因三端没有对等实现而保持在共享契约之外。

## Iteration 125-126 已解决

- Python HTTPServer、FastAPI 与 Express Core 代理已对齐角色列表、角色详情、按角色/能力调度和批量调度，并纳入共享 OpenAPI `1.11.0`。
- 两个 Python 服务状态现在把各自唯一的 `OllamaManager` 注入 `AgentFactory`；生产角色 handler 使用角色提示和原始任务执行真实非流式 Ollama chat，不再返回确定性 “Task received” 占位响应。
- `JARVIS_ROLE_MODEL` 以受信任进程配置选择角色模型，默认 `llama3.2`；角色 `tools` 仍只是提示元数据，不获得终端或插件权限。
- 上游错误、异常和空 assistant 内容统一收敛为稳定的 `Ollama role execution failed` 调度错误；fixture 生成的角色 Token 同步进入现有会话遥测。
- 三端真实 loopback harness 断言 fixture 回复 `OK`，并按共享 manager 边界验证 Python Core、FastAPI 与 Express 的精确 Token 样本。

## Iteration 127 已解决

- `_RegisteredAgent` 现在区分已结束 handler 错误与可能仍在运行的 timeout：两者对外仍是 `error` 状态，但只有普通错误带内部可恢复标记。
- `Orchestrator.recover_agent()` 提供线程安全的 recoverable `ERROR -> IDLE` 转换，不修改失败结果、历史、错误计数或聚合统计。
- `AgentFactory` 在向调用者返回原始错误后恢复角色，使下一次独立请求可再次执行；不会隐藏重试失败的请求。
- timeout 明确标记为不可恢复，避免 daemon handler 尚未退出时接受重叠任务。

## Iteration 128 已解决

- 新增默认拒绝的 `RoleToolPolicy` 与 `RoleToolBroker`；角色声明、精确授权和已注册 handler 必须同时满足，工具调用才可到达 handler。
- 未声明、未授权和未注册分别产生稳定拒绝原因，拒绝发生在执行前；决策写入线程安全的有界内存审计记录。
- `AgentFactory` 默认使用空 broker，系统提示明确输出 `[TOOL ACCESS] disabled`，不再把 profile 声明误称为可用工具。
- 任务元数据拆分为 `declared_tools` 与 `authorized_tools`，为后续模型工具循环保留可验证边界，但本轮不启用自动工具调用。
- Phase 3 评估 Kontext CLI 与 Doberman Core；两者均是更大的外部控制面，当前只借鉴执行路径强制和 fail-closed 原则，不新增依赖。

## Iteration 129 已解决

- 新增版本化 `RunState`、工作包状态和精确下一动作约束，修订号只能单调递增。
- 新增上下文 Green/Yellow/Red 水位监控；Red 会持久化停止调度的恢复 checkpoint。
- 新增固定章节恢复文档、统一秘密脱敏和 HMAC 认证文件仓库，状态、清单、事件链与文档使用原子替换。
- 新增 Git HEAD/分支/脏路径漂移检测和恢复优先级；FastAPI 在开始服务前只恢复一次 active run，并对完整性失败保持 fail-closed。
- 组合门禁覆盖 Red 水位、脏工作树和部分工作包同时存在时，恢复结果仍只有一个安全下一动作。

## Iteration 130 已解决

- 新增协议版本 `1` 的 Worker 请求、事件和任务记录，父进程是任务状态唯一权威。
- 新增 Windows `spawn` 兼容的 `RoleWorkerSupervisor`，覆盖成功、失败、崩溃、超时、取消、迟到事件、历史上限和 shutdown 清理。
- `timeout` 与 `cancelled` 只有在子进程确认退出后才能发布；固定生产 runner 在子进程内构造 Ollama 与角色依赖，并把 Token 用量回写父进程。
- FastAPI 新增角色任务创建、列表、详情和取消 API；HTTP 不能选择 runner、命令、环境、工作目录或 capability token。
- OpenAPI 升级到 `1.12.0`，声明 Worker task schema、成功/错误响应，并用条件 schema 约束终止确认。
- 旧同步角色 dispatch 保持兼容且仍不可取消；持久任务恢复与旧路径迁移继续作为 Phase B 后续工作。

## Iteration 132 已解决

- 三条同步角色路由（按角色、按能力和批量）现在通过 `RoleDispatchService`、`RoleWorkerSupervisor` 和固定生产 runner 执行，兼容既有响应形状与批量输入位置顺序。
- Python HTTPServer、FastAPI 和 Express Core API 代理均使用较长的 Worker 传输预算，并将可用性、未确认终止和无效 Worker 结果映射为一致的稳定错误。
- Express E2E 端口可由 `JARVIS_E2E_PORT` 隔离，避免占用既有开发服务器。
- `/api/orchestrator/dispatch` 未迁移，保持原有通用编排行为；异步角色任务持久恢复和默认拒绝 Broker 上的模型工具循环仍是明确的 Phase 11 后续项。

## Iteration 133-134 已解决

- 角色任务记录使用原子 JSON 文件持久化；FastAPI 启动时在 run-state 恢复后核对孤儿记录并形成明确终态，不尝试恢复已丢失的 Worker 进程。
- 模型工具循环只在生产 `RoleWorker` 内启用；严格的工具协议、参数 Schema、调用次数、输入/输出字节与总时限预算共同约束每一轮调用。
- 固定只读目录仅包含系统状态、模型列表、编排器状态、Memory 查询和仓库元数据，结果统一脱敏并写入有界审计。
- 终端执行、Plugin 生命周期、HTTP capability token 与通用 `/api/orchestrator/dispatch` 均未进入该目录或迁移范围。

## Iteration 135 已解决

- 新增 schema version 1 的 Skill、Plugin 和 UI 组件能力记录，统一声明生命周期、权限、兼容约束、来源、摘要、健康与风险。
- 新增固定可信根的只读发现器；只扫描直接子项，不跟随符号链接、不导入 Plugin，并对文件数和读取字节设置上限。
- 未知版本、来源和许可证保持显式未知；畸形 Plugin 清单形成 `invalid` 高风险记录，不会被静默遗漏或中断其他发现。
- 当前真实快照包含 22 条记录：19 个 Skill、2 个 Plugin、1 个直接导出的 UI 组件，无扫描级错误。
- Phase 3 桥接结论为本地能力已覆盖 D1 实现需求，本轮不新增依赖或外部部署。

## Iteration 138 已解决

- 新增最多 64 个不可变修订版的显式升级；只有当新内容发布和索引替换都成功后才切换当前指针。
- 回滚和删除回退在写入索引前重新验证 bundle、Manifest 与实际 payload；漂移修订版不会被标记为当前版本。
- 删除使用同目录 tombstone 与失败恢复，最后一个修订版删除后才移除能力记录，未知兄弟内容保持不变。
- 重建可在重启后从已存 bundle 和 payload 原子修复状态；已声明文件改写或额外 payload 注入均以 `REVISION_DRIFT` 失败关闭。
- 同根实例共享 `RLock` 串行写入，安装、升级、回滚与重建仍不导入、不执行且始终保持 `disabled`。

## Iteration 137 已解决

- `FileCapabilityStore` 只接受调用方已提供的 ZIP 字节和匹配的 SHA-256；不下载、不导入、不执行，也不会自动启用能力包。
- 验证覆盖压缩归档大小、条目数量、解压总量、单文件大小、路径、编码、链接、加密、压缩方式、布局和 Manifest；仅允许 MIT、Apache-2.0、BSD-2-Clause 与 BSD-3-Clause。
- 通过临时同级目录和 `os.replace` 发布内容寻址修订版；公开状态仅含相对 POSIX 路径，精确重试幂等，损坏状态和重解析点失败关闭。

## Iteration 136 已解决

- 新增最多八子句的数字版本约束，只支持明确的等于和大小比较；通配符、caret、预发布与超大版本组件全部拒绝。
- 新增不可变运行时目标与有界查询，按类型、最大风险、兼容状态和 `1..100` 结果数过滤。
- 本地解析以 ID/名称精确匹配、Token、描述和质量信号评分，并用 capability ID 稳定打破同分。
- 不支持或未提供的运行时保持 `unknown`，不兼容约束保持 `incompatible`；公共结果覆盖求值状态但不修改原始快照。
- Phase 3 桥接结论为现有本地能力足以完成解析器，本轮未新增依赖或外部部署。

## 四维评分

| 维度 | 得分 | 依据 |
|---|---:|---|
| 可维护性 | 95 | POST/GET SSE 路径均由 OpenAPI 和真实三服务 harness 回归，Python 适配器复用单一写入路径 |
| 扩展性 | 95 | 角色工具 broker、版本化能力记录和无状态解析器分别隔离执行、发现与选择 |
| 性能 | 84 | 前端按视图拆包，重型视图仍需低端设备实测 |
| 安全性 | 94 | HTTP 终端和角色工具默认拒绝；能力发现不跟随符号链接、不导入代码并限制读取预算 |

## 技术债清单

| 位置 | 严重程度 | 问题 | 修复建议 |
|---|---|---|---|
| 内部通用终端执行器 | P1 | 默认实例已有最小环境和专用目录，但仍运行于服务用户上下文 | 将脚本能力迁移到低权限 worker；不得再次暴露为通用 HTTP/Plugin API |
| Express-only Git API | P1 | OpenAPI `1.12.0` 已覆盖共享 orchestrator、角色路由和异步角色任务；`/api/git/*` 仍是仅由 Express 提供的稳定实现面 | 用独立契约或明确的 OpenAPI 扩展记录 Git 响应与错误 schema |
| 能力注册与安全部署 | 进行中 | D1-D4 只读目录、兼容解析、包验证和可逆生命周期已完成；API/UI 尚未交付 | 完成 Iteration 139 只读契约与视图，并保持默认禁用和无网络输入 |
| 角色工具执行策略 | 已完成 | Worker 内固定五工具目录、严格 Schema、预算、默认拒绝 Broker 与脱敏审计均已落地 | 保持终端、Plugin 生命周期和 HTTP capability token 在目录之外 |
| 异步任务持久恢复 | 已完成 | 任务记录在 shutdown 时持久化，启动时核对孤儿 Worker 并恢复明确终态 | 后续存储演进必须保留原子写入和 fail-closed 恢复语义 |
| 本机真实集成 | 已完成 | CI 使用仓库自有 Ollama fixture、FastAPI 与 Express 临时端口运行 `--require-services` | 保留真实 Ollama 工作站 profile 作为可选补充 |
| 重型前端视图 | P2 | Chat/Runtime chunk 约 198/215 kB | 低端设备测量后再决定拆包 |

## 剩余风险

### P1：内部通用终端执行器

HTTP 路径不再直接使用通用 `TerminalExecutor` 的宽松 allowlist；默认内部实例现在使用最小环境和实例专属工作目录，且拒绝调用者环境与路径覆写。但它仍在服务用户上下文中运行，没有 OS 级隔离。

已完成：默认 HTTP 服务终端已迁移到进程隔离 `TerminalWorker`，使用专用临时目录、最小环境、固定只读操作和可选 POSIX UID/GID 降权；通用 `TerminalExecutor` 仍仅供显式内部注入，不再作为 HTTP 默认入口。

### P1：多套 API 行为漂移

Express、Python HTTPServer 和 FastAPI 已由共享 OpenAPI 文件约束健康、系统遥测、Ollama 状态/模型、Token、插件、记忆、事件、共享 orchestrator、角色路由、异步角色任务、首批写操作错误、非流式 Ollama chat 与 GET/POST 规范 SSE 帧。Express Git 失败和未知 API 路由也已使用稳定 ErrorResponse，但 `/api/git/*` 仍是未纳入共享契约的 Express-only 实现面。

已完成：OpenAPI 升级到 `1.12.0`，增加 Express-only `x-jarvis-api-fallback`，并为 Ollama、Core API、共享 orchestrator、角色路由与异步角色任务声明请求、响应和 `ErrorResponse`。Python HTTPServer 不提供异步任务生命周期，Express-only `/api/git/*` 继续保持显式实现范围，不能被误称为三端共享能力。

### P1：真实集成仍依赖本机服务

Playwright 使用确定性 API fixture 验证 UI；真实 Ollama、Express、FastAPI 流程已有可选 profile，但当前默认验证环境没有持续运行 Ollama。

已完成：GitHub Actions 通过 `scripts/ci_local_integration.py --require-services` 启动仓库自有 fixture、FastAPI 与 Express，验证真实 HTTP/SSE、记忆与插件路径，并在退出时清理子进程和临时数据。

### P2：前端重型视图仍有优化空间

Markdown 和 Chart.js 已按视图懒加载，但对话与运行监控生产 chunk 仍分别约 198 kB 和 215 kB。

下一步：在真实低端设备上测量交互延迟，再决定是否拆分 Markdown/Chart.js 或按需加载图表。

### 已完成：受控角色工具调用

默认拒绝的策略与 broker 已落地，角色声明、显式授权和已注册 handler 必须同时匹配，拒绝决策不会到达 handler。生产 `RoleWorker` 可解析 Ollama 工具请求，但只能调用固定五工具只读目录；严格 Schema、调用/字节/时间预算、秘密脱敏和有界审计共同生效。普通 `AgentFactory`、终端、Plugin 生命周期、HTTP capability token 和通用 orchestrator dispatch 不获得该能力。

### P1：timeout 后的执行隔离

FastAPI 的异步角色任务通道与三条同步角色 dispatch 都由父进程拥有权威记录的 Worker 路径执行：timeout/cancelled 必须等待子进程确认退出，迟到事件不能覆盖终态。无法确认终止的 Worker 会保持 resident 并阻止同角色复用，这是有意的 fail-closed 行为。任务记录在 shutdown 时持久化，启动时把已丢失进程的孤儿记录核对为明确终态。`asyncio.to_thread` 避免 FastAPI 同步 Worker 操作阻塞事件循环，但 HTTP 协程被取消后底层调用仍可能完成。通用 `/api/orchestrator/dispatch` 保持既有行为，不能把 Worker 通道的保证倒推到该路由。

### P2：恢复仓库极端崩溃耐久性

恢复仓库现在通过不可变 revision、文件内容 `fsync`、原子 manifest 切换和同根读写锁防止并发回退或读到被提前清理的快照。POSIX 清理会在每次删除前复核目录身份；Windows 和缺少安全 descriptor API 的平台不自动清理旧 revision/staging。父目录元数据尚未显式执行目录 `fsync`，非协作的同用户进程仍可能在身份检查与删除之间制造极窄竞态；未知或持续不可删除内容会按安全优先策略保留。

## 维护规则

1. `src/` 保持 Python-only；前端 TypeScript 统一放在 `frontend/src/`。
2. `docs/reports/` 只滚动保留最近 10 份 `AUDIT_REPORT_N.md`。
3. `CHANGELOG.md` 保留最近 10 个迭代摘要；长期事实写入当前分析或协议。
4. API 和 UI 不显示伪造数据；能力不可用时呈现明确状态。
5. 每次交付运行 Python 聚合/完整测试、前端 Vitest、Playwright、TypeScript typecheck 和生产构建。
