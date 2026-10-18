# 小奕 J.A.R.V.I.S. 当前项目分析

**分析时间**：2026-10-19
**最新功能迭代**：Iteration 257
**判断依据**：当前代码、配置、工作树和本次验证结果

历史迭代的完整叙述不放在本文件。请从 [报告索引](README.md) 查看最近十轮审计，从 [CHANGELOG.md](../../CHANGELOG.md) 查看完整台账；旧版分析正文保存在历史清理归档中。

## 当前结论

项目已经具备一条可运行的本地指挥中心链路：Solid.js 前端通过 Express 访问 Ollama，并按需桥接 Python Core。Python Core 提供标准库 HTTPServer 和 FastAPI 两个替代入口；FastAPI 额外提供异步角色任务、任务状态和生命周期恢复。

核心执行边界已经从服务进程拆到父端拥有的 Worker：角色任务使用可终止进程，Plugin 使用 `python_worker` 和默认拒绝 Broker，固定终端使用独立 Worker。能力发现、记忆访问和角色工具目录都是有界、确定性和只读优先的实现。

Phase F 已完成：记忆可解释、可删除、可迁移。当前实现同时支持确定性词法检索、FTS5 trigram 全文检索、可选本地语义检索、SQLite 派生索引、导出导入、校验备份恢复和显式条目级保留策略。Markdown 文件仍是唯一权威来源，索引和向量都可以重建。

当前主要缺口不是记忆功能，而是不同服务入口之间的请求适配仍有重复、部分平台隔离证据依赖对应 CI runner，以及角色任务只做启动对账、不自动重放未完成任务。

## 模块地图

| 模块 | 主要入口 | 当前职责 |
|---|---|---|
| 前端 | `frontend/src/main.tsx`、`frontend/src/App.tsx` | 六个工作视图、共享轮询、SSE 对话和 Core API 客户端 |
| Express | `frontend/server.js`、`frontend/server/` | Ollama/SSE、系统与 Token 遥测、Git 只读接口、Core API 代理 |
| Python 服务 | `src/main.py`、`src/main_fastapi.py` | 健康、模型、记忆、Plugin、角色、终端和编排 API |
| Brain | `src/core/brain/` | 角色注册、Agent 工厂、Worker 调度、DAG、工具循环和上下文压缩 |
| Kernel | `src/core/kernel/` | Ollama、Terminal Worker、Plugin Broker、事件总线、能力注册和隔离 |
| 适配器 | `src/adapters/` | 文件状态、能力包、角色任务、SQLite 索引、嵌入和子进程运行时 |
| 扩展 | `plugins/`、`skills/` | 两个第一方 Plugin 和 19 个本地 Skill 说明包 |
| 契约 | `contracts/core-api.openapi.json`、`src/core/contracts/` | HTTP、Worker、角色工具、检索和运行状态 Schema |

## 请求与执行流

```text
浏览器 :5173
  -> Express :9999
       -> Ollama :11434                  对话、模型、遥测
       -> Python Core :8080              记忆、Plugin、角色、终端、能力注册
            -> 父端拥有的 Worker       角色任务、Plugin 生命周期、固定终端
```

Express 未配置 `JARVIS_CORE_API_URL` 时仍能提供自身的对话、监控、模型和仓库视图；Core 依赖会明确返回未配置状态。Python HTTPServer 与 FastAPI 不能同时占用 8080。

## 已交付能力

### 角色、Worker 与工作流

- 五个基础角色加两个继承角色由 `RoleRegistry` 管理。
- `/api/roles/dispatch` 及 FastAPI 异步任务通过 `RoleWorkerSupervisor` 启动可终止进程。
- 生产 Worker 只绑定五个固定只读工具：`system_status`、`model_list`、`orchestrator_status`、`memory_search`、`repository_metadata`。
- 父端验证角色声明、Registry 装配证据、Schema、调用次数、参数/结果字节数和总时限；普通 `AgentFactory` 默认没有工具权限。
- Workflow DAG 支持拓扑分层、同层受限并行、`fail_fast` 和 `continue`；上限为 512 节点、4096 条边和 16 路并行。
- 所有 Workflow 节点复用既有角色 Worker 调度，不新增命令、环境或能力选择入口。

### 记忆与上下文

- `MemoryStore` 支持 v2 无损 JSON/Markdown 信封和 v1 只读兼容。
- Markdown 文件是唯一权威来源；SQLite 元数据、FTS5 索引和嵌入向量均为可重建派生数据。
- 检索支持默认词法模式、`mode=fulltext` 和可选 `mode=semantic`；语义模式仅在显式配置 `JARVIS_MEMORY_EMBED_MODEL` 时启用。
- 写入、索引、删除和恢复使用有界读写、意图日志、原子替换和目录持久化契约。
- `SemanticCompressor` 负责重要性、过期、截断、摘要和无损合并；重复变换保持幂等。
- 固定 `memory_search` 使用有界词法分词、确定性排序、脱敏片段和 `source_ids` provenance。
- 已支持有界导出导入、自描述 SHA-256 校验备份、非破坏恢复和默认关闭的条目级 prune。
- `MemoryRepository` v2 端口和统一符合性检查已冻结可替换存储后端需要满足的行为边界。

### Plugin、能力与平台边界

- `CapabilityRegistry` 只读扫描 Skill、Plugin、Role Tool 和 UI 元数据。
- `FileCapabilityStore` 只接受调用方提供的 ZIP 字节，经内容、Manifest、许可证、入口和树边界校验后以 disabled 版本暂存。
- `PluginManager` 通过 `SubprocessPluginRuntime` 拥有 Worker 生命周期；Broker 默认拒绝。
- 第一方 Plugin 默认只授予 `event.emit`；只读文件、系统状态和配置能力必须显式声明、授权并注册父端 handler。
- Linux 使用 network namespace/Landlock，Windows 使用 capability-free AppContainer，macOS 使用 Seatbelt；真实内核证据受运行平台限制。
- `/api/terminal/execute` 默认关闭，必须同时启用运行时开关和提供能力 Token，且只接受五个固定诊断操作。

### 前端与服务

- 前端视图为 Chat、Runtime、Repository、Models、Memory、Plugins；导航没有 URL 路由。
- 共享轮询资源负责系统、Token、Git 和 Ollama/Core 状态，支持隐藏页面暂停、取消、退避和 stale 状态。
- SSE、HTTP body/query、Git 子进程和 Core 代理都有独立字节预算。
- OpenAPI 1.17.0 维护三服务共享响应契约，并明确 Express-only Git 接口边界。

## 当前规模

| 范围 | 文件数 | 非空行（约） |
|---|---:|---:|
| `src/` Python | 63 | 25,634 |
| `frontend/src/` TS/TSX | 39 | 4,885 |
| `tests/` Python | 91 | 39,259 |
| `skills/` | 19 个目录 | - |
| `plugins/` | 2 个第一方目录 | - |
| 顶层审计报告 | 10（Iteration 248-257） | - |

## 四维评分

评分是当前工程判断，不是自动化测试指标；每次实质迭代应结合代码和验证重新评估。

| 维度 | 得分 | 依据 |
|---|---:|---|
| 可维护性 | 94 | 模块边界、共享契约、聚合测试和当前文档入口明确 |
| 扩展性 | 94 | Registry、Broker、Worker、DAG、记忆端口和派生索引可独立演进 |
| 性能 | 84 | 前端已有拆包和共享轮询，Chat/Runtime 仍需低端设备实测 |
| 安全性 | 95 | 默认拒绝、输入/输出预算、进程隔离和平台边界已覆盖主要路径 |

## 技术债与路线

| 优先级 | 问题 | 下一步 |
|---|---|---|
| P1 | 不同服务入口仍存在重复的请求适配和状态组装 | 继续提取共享 Core 组件，新增接口时同步 OpenAPI、Python 和 Express 行为 |
| P1 | Windows/macOS 的部分强制证据依赖对应主机或 CI runner | 保留明确的 skip 语义，补齐非 skip 的 hosted-runner 证据后再扩大声明 |
| P2 | Chat/Runtime 前端 chunk 较重 | 在真实低端设备测量交互延迟后，再决定按 Markdown、图表和视图拆分 |
| P2 | 角色任务持久化是 shutdown 快照，不能自动恢复执行 | 只有在定义幂等任务、身份验证和重复执行语义后，才设计可重放恢复 |
| P2 | 语义检索默认关闭且覆盖率取决于本地嵌入模型 | 在目标设备上测量索引补齐成本、召回质量和离线降级行为后再调整默认值 |

## 验证入口

- Python 聚合：`venv\Scripts\python.exe tests/run_all.py`
- Python 完整发现：`venv\Scripts\python.exe scripts/discover_tests.py --timeout 1800`
- 语法和 lint：`venv\Scripts\python.exe -m compileall -q src tests scripts`、`python -m ruff check src tests scripts`
- 前端：在 `frontend/` 执行 `npm test -- --run`、`npm run test:e2e`、`npm run typecheck`、`npm run build`
- 本地联调：`scripts/local_integration_profile.py`；确定性 CI 夹具：`scripts/ci_local_integration.py --require-services`

Iteration 257 的审计快照记录 Python 聚合测试 1258 个（1247 通过、11 跳过）和前端 Vitest 159 个通过。当前结果应以重新执行上述命令为准。

## 维护规则

1. 先读 `git status` 和相关差异，再按模块形成可回滚变更。
2. 代码变更必须有与影响范围相称的回归验证；不以删除测试或放宽边界换取通过。
3. 新能力先更新契约和当前分析，再更新实现与测试；历史细节写入审计报告和 `CHANGELOG.md`。
4. 临时输出使用 `.test-*` 并保持忽略；可保留的证据放在 `artifacts/`，不要回到源码或报告根目录。
