# 小奕 J.A.R.V.I.S. 项目分析（每日自动扫描）

**扫描时间**：2026-07-21

**扫描范围**：`C:\GitHub\贾维斯\`（排除 `.git`、`node_modules`、`venv`、`dist`、`.worktrees`）

**依据**：实际文件树、服务入口、配置、git 历史与本轮沙箱静态检查

**分支**：`codex/iteration-101-core-contracts`（HEAD `ad00d03`）

> 说明：本文件由每日自动扫描任务生成于仓库根目录。项目维护的规范分析文件仍是 `docs/reports/PROJECT_ANALYSIS.md`，判断长期状态时以该文件、代码和 Windows 环境的完整测试结果为准。

## 结论

项目是一个本地优先的自主演进引擎，覆盖任务编排、Ollama 模型访问、受控终端执行、插件生命周期、上下文压缩与可视化监控。前端是 Solid.js 六视图指挥中心，通过统一 API/SSE 客户端消费 Express；Express 提供真实系统/Git/Ollama 数据并可选桥接 Core API。Python HTTPServer 与 FastAPI 作为可替换的核心服务入口。

**当前处于 Iteration 132 进行中状态。** 记录的最新已定稿迭代为 131（原子恢复发布 + 角色任务生命周期加固）。git 历史显示 131 定稿后又有 7 个提交，正在把旧同步角色 dispatch 迁移到可终止的进程 Worker：新增 `role_dispatch_service.py` 共享同步兼容服务，Supervisor 已可等待/可观察，FastAPI 适配器已切换到 `asyncio.to_thread`。工作树仍有大量未提交改动（`src/main.py`、Express 代理、OpenAPI 契约、测试聚合），Iteration 132 尚未定稿。

## 当前规模（本轮实际盘点）

| 范围 | 盘点结果 | 与 131 基线对比 |
|---|---:|---|
| `src/` Python | 29 个文件 | +1（新增 `role_dispatch_service.py`） |
| `src/` TypeScript | 0 个文件 | 不变 |
| `frontend/src/` | 38 个 TS/TSX 文件 | 不变 |
| `tests/` Python | 50 个 `test_*.py` | +1（新增 `test_role_dispatch_service.py`） |
| 本地 Skill | 19 个目录 | 不变 |
| Plugin | 2 个（`plugin-template`、`event-logger`） | 不变 |
| 滚动审计报告 | 10 份（Iteration 122-131） | 不变 |

## 运行架构

| 服务 | 默认端口 | 职责 |
|---|---:|---|
| Vite | 5173 | Solid.js 指挥中心开发服务器与 Express 代理 |
| Express | 9999 | Ollama SSE、系统/Token 遥测、Git 数据与 Core API 桥接 |
| Python HTTPServer | 8080 | 标准库兼容 API |
| FastAPI | 8080 | 插件、角色、多代理、异步角色任务与完整 Core API |
| Ollama | 11434 | 本地模型运行时 |

Python HTTPServer 与 FastAPI 是替代入口，不能同时监听 8080。三种服务默认只监听 `127.0.0.1`，未设置 CORS 时仅允许两个本地 Vite origin。

## Iteration 132 进行中（git 历史证据）

- `role_dispatch_service.py`（新增，309 行）：brain 层共享同步兼容服务。负责角色/能力选择、每角色单活跃请求同步租约、生成外层 Worker 任务 ID、向 `RoleWorkerSupervisor` 提交 `WorkerTaskRequest`、等待终态记录、严格解码四字段 dispatch 载荷、把终态映射为 `DispatchResult`。不拥有进程、Ollama 客户端或 HTTP 响应；不重复记录 Token。
- 定义三类异常（`RoleWorkerUnavailableError`、`RoleTaskTerminationUnconfirmedError`、`RoleWorkerInvalidResultError`），适配器将其转为稳定 `503` envelope。
- Task 1（`028515a`）：Supervisor 变为可等待/可观察（`wait`、`terminal_wait_budget`、`add_terminal_observer`、条件变量通知、锁外回调）。
- Task 2（`d35c59e`）：`AgentFactory.execute_role_once` 单一截止时间直接执行；子进程 Ollama `timeout=None`。
- Task 3（`908a7cd`）：落地服务本体。
- Task 4（`5fb8759`+`ad00d03`）：FastAPI 适配器迁移到 `asyncio.to_thread`，共享 Supervisor 生命周期。
- **未完成（Task 5-7 未提交）**：`src/main.py` 标准库适配器、Express 预算与代理、`contracts/core-api.openapi.json`、`tests/run_all.py` 聚合、`AUDIT_REPORT_132.md`。工作树另有 `RISK_COMPONENTS.log` 删除与一个 `.git/index.lock` 残留。

## 四维评分

| 维度 | 得分 | 依据 |
|---|---:|---|
| 可维护性 | 94 | 三套服务由共享 OpenAPI 与真实三服务 harness 约束；同步 dispatch 迁移期出现临时双路径，定稿前维护面略增 |
| 扩展性 | 92 | 角色工具 broker 与可等待/可观察 Supervisor 为后续受控执行和持久恢复提供清晰边界 |
| 性能 | 84 | 前端按视图拆包，Chat/Runtime chunk 约 198/215 kB，重型视图仍需低端设备实测 |
| 安全性 | 93 | HTTP 终端与角色工具默认拒绝；异步/迁移中的同步通道均以进程 Worker 加可确认终止为准 |

## 技术债清单

| 位置 | 严重程度 | 问题 | 修复建议 |
|---|---|---|---|
| 旧同步调度迁移 | P0（进行中） | FastAPI 已迁移到进程 Worker，`src/main.py` 标准库适配器（Task 5）与 Express 预算（Task 6）尚未提交，迁移处于半完成状态 | 完成 Task 5-7 并定稿 Iteration 132；迁移完成前不得宣称标准库路径可安全取消 |
| 内部通用终端执行器 | P1 | 默认实例已用最小环境和专用目录，但仍运行于服务用户上下文，无 OS 级隔离 | 保持仅限显式内部注入，不再暴露为通用 HTTP/Plugin API |
| Express-only Git API | P1 | `/api/git/*` 仍是仅 Express 提供的稳定实现面，未纳入共享契约 | 用独立契约或 OpenAPI 扩展记录 Git 响应与错误 schema |
| 角色工具自动调用 | P1 | 默认拒绝 broker、精确授权、handler 注册与有界审计已落地，模型工具循环未接入 | 只为固定只读能力注册 handler，每次模型工具请求强制经过 broker |
| 异步任务持久恢复 | P1 | Worker 状态由父进程内存权威维护，服务重启后无持久任务核对 | 将任务记录接入 RunState，启动时核对孤儿 Worker 后再确定终态（计划 Iteration 133） |
| 重型前端视图 | P2 | Chat/Runtime chunk 约 198/215 kB | 低端设备测量后再决定拆包 |

## 演进路线图

### P0 — 收敛当前迁移（Iteration 132 定稿）

完成同步 dispatch 迁移的 Task 5-7：`src/main.py` 标准库适配器接入 `role_dispatch_service`、Express 预算与四路代理对齐、更新 `contracts/core-api.openapi.json` 与 `tests/run_all.py` 聚合、生成 `AUDIT_REPORT_132.md`。清理工作树残留（`.git/index.lock`），按模块形成可回滚提交。

### P1 — 执行边界与契约

将异步/同步角色任务记录接入 RunState 并实现启动恢复（Iteration 133）；为固定只读能力接入受 broker 强制的模型工具循环；用独立契约记录 Express-only `/api/git/*`。

### P2 — 性能与耐久性

在真实低端设备测量 Chat/Runtime 交互延迟后再决定是否拆分 Markdown/Chart.js；补齐恢复仓库父目录 `fsync` 与跨平台清理耐久性。

## 本轮验证边界（诚实声明）

本次扫描运行在 Linux 沙箱，项目 `venv` 为 Windows 专用，无法复用。已完成与未完成的验证：

- 已验证：`src/` 在系统 Python 3.10 下 `compileall` 通过（exit 0）。
- 已验证：文件树盘点、git 历史、模块结构与 131 基线的实际差异。
- 未运行：`tests/run_all.py` 聚合套件——依赖 `tomllib`（需 Python 3.11+），沙箱为 3.10.12。
- 未运行：前端 Vitest/Playwright/typecheck/build 与本机集成 profile——需 Windows `venv` 与 Node 环境。
- 131 记录的完整基线（聚合 295 共 293 通过 2 跳过；discovery 1170 共 1168 通过 2 跳过）在 Windows 环境验证，本轮未复现。

Iteration 132 的测试结果须在 Windows 环境按 `AGENTS.md` 验证基线补跑后才能作为当前状态确认。

## 维护规则

1. `src/` 保持 Python-only；前端 TypeScript 统一放在 `frontend/src/`。
2. `docs/reports/` 只滚动保留最近 10 份 `AUDIT_REPORT_N.md`。
3. `CHANGELOG.md` 保留最近 10 个迭代摘要；长期事实写入规范分析或协议。
4. API 和 UI 不显示伪造数据；能力不可用时呈现明确状态。
5. 每次交付运行 Python 聚合/完整测试、前端 Vitest、Playwright、TypeScript typecheck 和生产构建。
