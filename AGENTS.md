# AGENTS.md - 小奕 J.A.R.V.I.S. 项目上下文

**项目名称**：小奕 J.A.R.V.I.S. 自主演进引擎

**项目路径**：`C:\GitHub\贾维斯\`

**最后更新**：2026-07-10

**最新迭代**：Iteration 92

## 项目目标

构建一个本地优先的智能系统，覆盖任务编排、Ollama 模型访问、受控终端执行、插件生命周期、上下文压缩和可视化监控。

## 单一来源

- 核心协议：`docs/protocols/JARVIS_核心指令.md`
- 启动与开发：`README.md`、`docs/SETUP.md`
- 当前项目分析：`docs/reports/PROJECT_ANALYSIS.md`
- 迭代台账：`CHANGELOG.md`
- 报告导航：`docs/reports/README.md`

历史审计报告只记录当时的交付证据。判断当前状态时，以代码、配置和本次测试结果为准。

## 当前架构

| 层 | 入口 | 职责 |
|---|---|---|
| Solid.js 前端 | `frontend/src/main.tsx` | Dashboard 与 Widget 展示 |
| Express 服务 | `frontend/server.js` | 前端 API、Ollama/SSE、系统和 Git 数据 |
| Python HTTP 服务 | `src/main.py` | 标准库 HTTP API，默认端口 8080 |
| FastAPI 服务 | `src/main_fastapi.py` | 更完整的异步 API 与角色调度入口 |
| Kernel | `src/core/kernel/` | Ollama、终端、插件、事件总线 |
| Brain | `src/core/brain/` | 上下文压缩、编排器、角色注册、Agent 工厂 |
| Plugin | `plugins/` | 插件模板与事件记录插件 |
| Skill | `skills/` | 19 个本地技能包 |

## 目录结构

```text
贾维斯/
├── README.md
├── CHANGELOG.md
├── AGENTS.md
├── pyproject.toml
├── Dockerfile
├── docker-compose.yml
├── docs/
│   ├── SETUP.md
│   ├── protocols/
│   └── reports/
├── frontend/
│   ├── server.js
│   ├── package.json
│   └── src/
├── plugins/
├── skills/
├── src/
│   ├── main.py
│   ├── main_fastapi.py
│   └── core/
├── tests/
└── scripts/
```

## 当前规模

- `src/`：11 个 Python 文件；服务端源代码统一使用 Python。
- `frontend/src/`：18 个 TypeScript/TSX 文件。
- `tests/`：35 个 Python 测试文件；规范聚合套件 113 个用例。
- `skills/`：19 个技能目录。
- `plugins/`：`plugin-template` 与 `event-logger`。
- `docs/reports/`：滚动保留最近 10 份审计报告，最新为 `AUDIT_REPORT_92.md`。

## 阶段状态

| 阶段 | 状态 | 当前证据 |
|---|---|---|
| Phase 1-5 | 已有交付 | 协议、分析、核心骨架和环境相关报告 |
| Phase 6 | 已有交付 | `PHASE6_INSTALLATION_REPORT.md` |
| Phase 7 | 进行中 | 19 个技能已落地，市场清单仍是历史快照 |
| Phase 8 | 进行中 | Plugin SDK、沙箱策略、2 个插件目录 |
| Phase 9 | 已有交付 | Solid.js Dashboard |
| Phase 10 | 进行中 | Widget 基础接口和多种监控组件 |
| Phase 11 | 进行中 | Python 编排器、角色注册与 TypeScript 多代理协议 |
| Phase 12 | 进行中 | Python 聚合/扩展测试与前端 Vitest |

## 启动方式

```powershell
# Python HTTPServer
python src/main.py

# FastAPI
.\venv\Scripts\python.exe -m uvicorn src.main_fastapi:app --host 127.0.0.1 --port 8080

# Express API
cd frontend
node server.js

# Vite 前端
cd frontend
npm run dev
```

默认开发地址：Vite `http://localhost:5173`、Express `http://localhost:9999`、Python/FastAPI `http://localhost:8080`。

## 验证基线

```powershell
# 规范 Python 聚合套件
.\venv\Scripts\python.exe tests/run_all.py

# 完整 Python discovery
.\venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"

# 静态 AST/语法检查
.\venv\Scripts\python.exe -m compileall -q src tests

# 前端测试与构建
cd frontend
npm test -- --run
npm run typecheck
npm run build
```

## 工作约束

- 修改前先阅读 `git status` 和相关差异，并按模块形成可回滚提交。
- 不覆盖、回退或删除来源不明的用户改动。
- 业务代码变更应有回归测试；交付前运行与影响范围相称的验证。
- Skill/Plugin 通过项目定义的权限与沙箱策略运行。
- 临时测试输出使用 `.test-*` 命名并保持 Git 忽略。
- 不把历史审计报告中的测试数量或阶段状态直接当作当前状态。
