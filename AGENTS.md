# AGENTS.md - 小奕 J.A.R.V.I.S. 项目上下文

**项目名称**：小奕 J.A.R.V.I.S. 自主演进引擎
**项目路径**：`C:\GitHub\贾维斯\`
**最后整理**：2026-09-18
**最新功能迭代**：Iteration 249

## 项目目标

构建一个本地优先的智能系统，覆盖任务编排、Ollama 模型访问、受控终端执行、插件生命周期、上下文压缩和可视化监控。

## 权威入口

- 快速概览：`README.md`
- 安装、运行和验证：`docs/SETUP.md`
- 工程规则、架构边界和演进路线：`docs/DEVELOPMENT_GUIDE.md`
- 长期协议：`docs/protocols/JARVIS_核心指令.md`
- 当前分析和审计导航：`docs/reports/README.md`
- 当前项目分析：`docs/reports/PROJECT_ANALYSIS.md`
- 完整迭代台账：`CHANGELOG.md`

历史审计只记录当时的交付证据。判断当前状态时，以代码、配置和本次测试结果为准。

## 当前架构

| 层 | 入口 | 职责 |
|---|---|---|
| Solid.js 前端 | `frontend/src/main.tsx` | 六视图指挥中心、共享轮询资源与响应式应用壳 |
| Express 服务 | `frontend/server.js` | Ollama/SSE、系统与 Token 遥测、Git 数据、Core API 桥接 |
| Python HTTP 服务 | `src/main.py` | 标准库兼容 API，默认端口 8080 |
| FastAPI 服务 | `src/main_fastapi.py` | 异步任务、角色调度和完整 Core API |
| Kernel | `src/core/kernel/` | Ollama、终端、Plugin Worker、Broker、事件总线和能力注册 |
| Brain | `src/core/brain/` | 角色注册、任务编排、上下文压缩和角色工具授权 |
| Plugin | `plugins/` | 由 `python_worker` 执行的插件模板与事件记录插件 |
| Skill | `skills/` | 本地技能说明和工作流包 |

浏览器请求通常经过 `Vite 5173 -> Express 9999 -> Ollama/Core API`。Express
只有在配置 `JARVIS_CORE_API_URL` 后才代理 Python Core；Python HTTPServer 与
FastAPI 是二选一的 8080 入口。

## 当前能力

- 角色任务通过可终止的进程 Worker 执行；固定 Role Worker 内置五个只读工具：`system_status`、`model_list`、`orchestrator_status`、`memory_search` 和 `repository_metadata`。
- 工具目录、角色授权、Schema、调用次数、字节数和时间预算都由父进程验证；终端、Plugin 生命周期和 HTTP capability token 不属于角色工具目录。
- MemoryStore 支持有界 Markdown 读写、v1 只读兼容、v2 无损往返、意图日志恢复、压缩合并和删除；`memory_search` 当前是本地有界的词法检索，语义向量检索仍属于 Phase F 后续包。
- Capability Registry 只读扫描 Skill、Plugin、Role Tool 和 UI 元数据；FileCapabilityStore 可验证并暂存禁用的 ZIP 版本，不会导入或执行未知包。
- Plugin 生命周期由父端拥有的 `python_worker` 控制。Broker 默认拒绝；第一方插件默认只获得 `event.emit`，其它只读能力需要明确声明、授权和父端注册。
- Linux Worker 使用 network namespace/Landlock；Windows 使用 capability-free AppContainer；macOS 使用 Seatbelt。平台强制证据和未验证范围见当前审计报告。

## 阶段状态

| 阶段 | 状态 | 说明 |
|---|---|---|
| Phase 1-6 | 已有交付 | 协议、核心骨架、环境和安装报告已完成 |
| Phase 7-8 | 进行中 | Skill 市场快照和 Plugin SDK/运行时持续维护 |
| Phase 9-10 | 已重构 | Solid.js 指挥中心、真实遥测和响应式导航已完成 |
| Phase 11 | 进行中 | Worker、任务恢复和固定角色工具循环已交付，继续维护边界契约 |
| Phase 12 | 进行中 | Python 聚合/发现测试与前端 Vitest/Playwright 持续运行 |
| Phase F | 进行中 | 当前已交付有界词法检索；SQLite、全文和本地嵌入仍待实现 |

Iteration 249 是当前审计入口，详情见 `docs/reports/AUDIT_REPORT_249.md`。
Iteration 240-248 的近期证据保留在报告根目录，Iteration 230-239 位于
`docs/reports/archive/`；更完整的历史以 `CHANGELOG.md` 为准。

## 目录约定

```text
贾维斯/
├── contracts/              跨服务 OpenAPI 契约
├── docs/                   设置、开发规则、协议和报告
├── frontend/               Solid.js/Vite 前端与 Express 服务
├── plugins/                Plugin manifest 与 python_worker 代码
├── scripts/                可重复执行的维护和验证工具
├── skills/                 本地 Skill 说明
├── src/                    Python 服务、Brain、Kernel 和适配器
├── tests/                  聚合测试、扩展测试和平台夹具
└── artifacts/              被忽略的清理副本与临时归档
```

`.test-*`、`__pycache__`、Ruff/Playwright 缓存和测试输出必须保持 Git 忽略；
需要保留的临时证据放在 `artifacts/cleanup/`，不要把一次性脚本放回根目录。

## 启动方式

```powershell
# Python HTTPServer 或 FastAPI 二选一
python src/main.py
.\venv\Scripts\python.exe -m uvicorn src.main_fastapi:app --host 127.0.0.1 --port 8080

# Express API
cd frontend
node server.js

# Vite 前端
cd frontend
npm run dev
```

默认地址：Vite `http://localhost:5173`、Express `http://localhost:9999`、
Python/FastAPI `http://localhost:8080`、Ollama `http://localhost:11434`。

## 验证基线

```powershell
.\venv\Scripts\python.exe tests/run_all.py
.\venv\Scripts\python.exe tests/run_all.py --smoke
.\venv\Scripts\python.exe scripts/discover_tests.py --timeout 1800
.\venv\Scripts\python.exe -m compileall -q src tests scripts

cd frontend
npm test -- --run
npm run test:e2e
npm run typecheck
npm run build
```

需要真实本地服务时使用 `scripts/local_integration_profile.py`；CI 等价夹具使用
`scripts/ci_local_integration.py --require-services`。命令、环境变量和可选服务说明统一见 `docs/SETUP.md`。

## 工作约束

- 修改前先阅读 `git status` 和相关差异，并按模块形成可回滚变更。
- 不覆盖、回退或删除来源不明的用户改动。
- 业务代码变更应有回归测试；交付前运行与影响范围相称的验证。
- Skill/Plugin 通过项目定义的权限与沙箱策略运行。
- 临时测试输出使用 `.test-*` 命名并保持 Git 忽略。
- 不把历史审计报告中的测试数量或阶段状态直接当作当前状态。
- 不使用 `git add .`、`git add -A` 或破坏性清理命令混入无关文件。
