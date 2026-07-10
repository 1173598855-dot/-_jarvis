# 小奕 J.A.R.V.I.S. 项目分析

**扫描时间**：2026-07-10

**扫描范围**：`C:\GitHub\贾维斯\`

**依据**：实际文件树、服务入口、配置、浏览器截图与本轮测试结果

## 结论

项目已从 Widget 聚合页重构为本地优先的六视图指挥中心。Solid.js 前端通过统一 API 客户端、SSE 客户端和共享轮询资源消费 Express；Express 提供真实系统/Git/Ollama 数据，并通过可选 Core API 桥接记忆、插件和事件能力。Python HTTPServer 与 FastAPI 继续作为可替换的核心服务入口。

当前工程重点从“建立可用界面”转为三项长期工作：统一三套服务的机器可读契约、迁移 FastAPI 生命周期钩子、把真实 Ollama/Core API 集成流程纳入持续端到端验证。

## 当前规模

| 范围 | 盘点结果 |
|---|---:|
| `src/` Python | 11 个文件，约 3,508 行 |
| `src/` TypeScript | 0 个文件 |
| `frontend/src/` | 38 个 TS/TSX 文件，约 4,186 行 |
| `tests/` Python | 35 个文件；34 个 `test_*.py` 模块，约 7,258 行 |
| 规范 Python 聚合套件 | 113 个用例 |
| 完整 Python discovery | 880 个用例 |
| 前端 Vitest | 61 个用例 |
| Playwright | 5 项通过，1 项按桌面条件跳过 |
| 本地 Skill | 19 个 |
| Plugin | 2 个 |
| 滚动审计报告 | 10 份（Iteration 84-93） |

## 运行架构

| 服务 | 默认端口 | 职责 |
|---|---:|---|
| Vite | 5173 | Solid.js 指挥中心开发服务器与 Express 代理 |
| Express | 9999 | Ollama SSE、系统/Token 遥测、Git 数据与 Core API 桥接 |
| Python HTTPServer | 8080 | 标准库兼容 API |
| FastAPI | 8080 | 插件、角色、多代理与完整 Core API |
| Ollama | 11434 | 本地模型运行时 |

Python HTTPServer 与 FastAPI 是替代入口，不能同时监听 8080。Express 在未配置 `JARVIS_CORE_API_URL` 时仍可提供对话、运行监控、模型和仓库视图；记忆与插件控制会如实显示能力不可用。

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

## 剩余风险

### P1：多套 API 行为漂移

Express、Python HTTPServer 和 FastAPI 的端点集合重叠，但错误格式、插件能力和流式行为仍未由同一份机器可读契约约束。

下一步：维护共享 API schema，并对同名端点执行跨实现响应测试。

### P1：真实集成仍依赖本机服务

Playwright 使用确定性 API fixture 验证 UI；真实 Ollama、Express、FastAPI 的联合启动仍属于手工集成流程。

下一步：增加可选的本机集成 profile，在服务可用时运行非模拟 SSE、记忆和插件流程。

### P1：FastAPI 生命周期 API 已弃用

`src/main_fastapi.py` 仍使用 `@app.on_event("startup")` 和 `@app.on_event("shutdown")`，测试输出持续产生弃用告警。

下一步：迁移到 FastAPI lifespan context manager。

### P2：前端重型视图仍有优化空间

Markdown 和 Chart.js 已按视图懒加载，但对话与运行监控生产 chunk 仍分别约 198 kB 和 215 kB。

下一步：在真实低端设备上测量交互延迟，再决定是否拆分 Markdown/Chart.js 或按需加载图表。

## 维护规则

1. `src/` 保持 Python-only；前端 TypeScript 统一放在 `frontend/src/`。
2. `docs/reports/` 只滚动保留最近 10 份 `AUDIT_REPORT_N.md`。
3. `CHANGELOG.md` 保留最近 10 个迭代摘要；长期事实写入当前分析或协议。
4. API 和 UI 不显示伪造数据；能力不可用时呈现明确状态。
5. 每次交付运行 Python 聚合/完整测试、前端 Vitest、Playwright、TypeScript typecheck 和生产构建。
