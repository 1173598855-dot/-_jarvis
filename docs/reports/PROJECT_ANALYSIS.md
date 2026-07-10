# 小奕 J.A.R.V.I.S. 项目分析

**扫描时间**：2026-07-10

**扫描范围**：`C:\GitHub\贾维斯\`

**依据**：实际文件树、Git 状态、配置、服务入口与测试结果

## 结论

项目已收敛为清晰的双运行时结构：`src/` 只承载 Python 服务与核心逻辑，`frontend/src/` 承载全部 TypeScript、Solid.js 组件和共享前端契约。旧迭代流水、一次性生成器、重复工作稿、缓存和无效 WSL 虚拟环境已清理。

当前工程重点从“清理历史堆积”转为三项长期工作：统一三套 API 的响应契约、迁移 FastAPI 生命周期钩子、为真实多代理执行建立端到端验证。

## 当前规模

| 范围 | 盘点结果 |
|---|---:|
| `src/` Python | 11 文件，约 3,503 行 |
| `src/` TypeScript | 0 文件 |
| `frontend/src/` | 18 个 TS/TSX 文件，约 1,212 行 |
| `tests/` Python | 35 文件，约 7,546 行 |
| 规范 Python 聚合套件 | 113 个用例 |
| 完整 Python discovery | 880 个用例 |
| 前端 Vitest | 11 个用例 |
| 本地 Skill | 19 个 |
| Plugin | 2 个 |
| 滚动审计报告 | 10 份（Iteration 83-92） |

## 运行架构

| 服务 | 默认端口 | 职责 |
|---|---:|---|
| Vite | 5173 | Solid.js 开发服务器 |
| Express | 9999 | Dashboard API、Ollama SSE、系统与 Git 数据 |
| Python HTTPServer | 8080 | 标准库兼容 API |
| FastAPI | 8080 | 插件、角色和多代理 API |

Python HTTPServer 与 FastAPI 是替代入口，不能同时监听 8080。Express 与 Python 两侧存在重叠端点，后续应由共享契约测试约束。

## 模块地图

```text
frontend/src/
  App.tsx
  components/*Widget.tsx
  core/brain/*-widget.ts
  core/brain/multi-agent-protocol.ts
  widget-engine/base-widget.ts

src/
  main.py | main_fastapi.py
  core/kernel/
    ollama_manager.py
    terminal_executor.py
    plugin_sdk.py
    event_bus.py
  core/brain/
    context_compressor.py
    semantic_compressor.py
    orchestrator.py
    role_registry.py
    agent_factory.py
```

## 本轮已解决

- 删除 60 份 Iteration 82 及以前的单轮审计报告，建立最近 10 轮滚动保留策略。
- 删除 8 个 `gen_*`、`write_*`、`_gen_*` 一次性代码生成器。
- 删除根目录重复 `PROJECT_ANALYSIS.md`，统一到 `docs/reports/`。
- 删除 19 MB 的 Linux/WSL `.venv`、测试状态、构建产物和 Python 缓存。
- 删除 `src/` 下 3 个空 TypeScript 文件和 5 个无消费者的重复 TypeScript 文件。
- 将多代理协议移动到前端真实消费目录，并新增 `npm run typecheck` 门禁。
- 将 `CLAUDE.md` 收敛为指向 `AGENTS.md` 的兼容入口。
- 将维护脚本从 8 个缩减为 2 个可重复执行工具，并新增用途说明。

## 剩余风险

### P1：多套 API 行为漂移

Express、Python HTTPServer 和 FastAPI 的端点集合重叠，但错误格式、插件能力和流式行为并未完全一致。

下一步：维护一份机器可读 API 契约，并对同名端点执行跨实现响应测试。

### P1：FastAPI 生命周期 API 已弃用

`src/main_fastapi.py` 仍使用 `@app.on_event("startup")` 和 `@app.on_event("shutdown")`，测试输出持续产生弃用告警。

下一步：迁移到 FastAPI lifespan context manager。

### P1：完整测试环境未统一

Windows `venv` 可运行聚合套件，但当前缺少 `pytest`；完整 discovery 暂由系统 Python 开发环境执行。

下一步：重新安装 `.[dev]`，并在 CI 与本地统一使用同一解释器入口。

### P2：测试运行器超时线程不可取消

`tests/run_all.py` 超时后只能返回，后台测试线程仍会执行到结束。真实慢套件可能与后续测试交叠。

下一步：将超时隔离改为子进程模型。

## 维护规则

1. `src/` 保持 Python-only；前端 TypeScript 统一放在 `frontend/src/`。
2. `docs/reports/` 只滚动保留最近 10 份 `AUDIT_REPORT_N.md`。
3. `CHANGELOG.md` 保留最近 10 个迭代摘要；长期事实写入当前分析或协议。
4. `scripts/` 只保存可重复执行的维护工具，不保留一次性生成器。
5. 每次交付运行 Python 聚合/完整测试、前端测试、TypeScript typecheck 和生产构建。
