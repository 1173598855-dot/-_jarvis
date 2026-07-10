# J.A.R.V.I.S. 日常控制中心全面优化设计

**日期**：2026-07-10

**状态**：已批准，进入实施计划

**范围**：Solid.js 前端、Express Dashboard API、相关测试与开发文档

## 1. 背景

当前 Dashboard 已具备本地模型聊天、Ollama 状态、系统资源、Git 状态和 Token 面板，但仍更接近演示页面而非日常工作台：

- 导航按钮没有实际切换行为，所有内容纵向堆叠在同一页面。
- 前端没有统一组件库、图标体系、类型化 API 客户端和资源状态模型。
- 各 Widget 独立轮询，错误大多只进入 `console`，状态和刷新时间无法统一。
- `GithubIntelligenceWidget` 与 `TokenUsageDashboardWidget` 通过 `innerHTML` 注入静态占位内容。
- Express 的 CPU 使用率固定为 `0`，Token 使用量由随机数生成，磁盘数据依赖逐步淘汰的 WMIC。
- 插件和事件端点在能力未连接时返回空数组，无法区分“确实为空”和“后端未启用”。
- 前端测试主要覆盖旧 Widget 字符串，缺少导航、流式对话、错误恢复与响应式浏览器验证。

本次优化将 Dashboard 重构为一个本地优先、任务优先、数据可信的日常控制中心，同时保留现有 Solid.js、Vite、Express 和 Python/FastAPI 运行时。

## 2. 已确认决策

| 决策项 | 结论 |
|---|---|
| 产品定位 | 可日常使用的控制中心，而非纯视觉演示 |
| 主布局 | 任务优先的三分区布局：主导航、弹性工作区、实时状态栏 |
| 默认语言 | 简体中文为主，模型名、Git、API 等技术标识保留英文 |
| 默认视觉 | “石墨精密”：中性深色表面、克制青绿操作色、语义化状态色 |
| 前端路线 | 保留 Solid.js，采用渐进式重构 |
| 组件与图标 | `@kobalte/core` + `lucide-solid`，项目 CSS Token 控制外观 |
| 数据原则 | 不展示随机、固定或无法证明来源的指标 |
| 后端路线 | 保留 Express BFF 与现有 Python/FastAPI，不进行框架迁移 |

## 3. 目标与非目标

### 3.1 目标

1. 建立可导航的六个工作视图：对话、运行监控、代码仓库、本地模型、记忆、插件与工具。
2. 建立一致、响应式、可访问的应用外壳和组件体系。
3. 用类型化 API 客户端统一请求、错误、取消、轮询、过期和刷新状态。
4. 让 CPU、内存、磁盘和 Token 指标来自真实采样或真实模型响应。
5. 在 Python/FastAPI 未连接时明确表达能力缺失，不将其伪装成空数据。
6. 补足单元、组件、服务端和浏览器测试，并验证桌面与移动端真实交互。
7. 保持现有核心服务、插件沙箱和终端权限策略不被前端绕过。

### 3.2 非目标

- 不迁移到 React、Next.js 或 shadcn/ui。
- 不在本次工作中合并 Python HTTPServer 与 FastAPI 的内部实现。
- 不新增未经现有后端支持的模型删除、Git 写入或任意终端执行按钮。
- 不实现账户、远程多租户、云同步或外部市场。
- 不把静态 GitHub 项目推荐继续作为控制中心的一级工作流。

## 4. 信息架构

### 4.1 应用外壳

`AppShell` 由四个稳定区域组成：

1. **主导航**：桌面端宽度 `216px`，提供六个工作视图；中等宽度折叠为图标栏。
2. **顶栏**：显示当前视图、整体服务健康和设置入口。
3. **主工作区**：弹性占满剩余空间，只渲染当前工作视图。
4. **实时状态栏**：桌面端约 `320px`，跨视图显示系统、Ollama、Git 与后台活动摘要。

底部活动栏用于显示后台任务、运行事件、告警和 Git 状态，可通过 Kobalte `Collapsible` 展开详情。

### 4.2 响应式行为

- `>= 1280px`：完整主导航、主工作区、实时状态栏同时显示。
- `768px - 1279px`：主导航折叠为图标栏，实时状态栏可收起。
- `< 768px`：单列工作区；底部导航保留“对话、运行、仓库、更多”；实时状态进入抽屉。
- 聊天编辑器固定在当前视图底部，但不得覆盖消息、活动栏或移动端导航。
- 动态指标、加载文案和状态标签使用稳定尺寸，避免数据刷新引发整体布局位移。

### 4.3 六个工作视图

| 视图 | 首阶段能力 |
|---|---|
| 对话 | 模型选择、流式消息、停止、失败重试、清空确认、快捷提示、Markdown/GFM 展示 |
| 运行监控 | 系统资源、服务健康、事件流、真实趋势、刷新时间与异常状态 |
| 代码仓库 | 分支、工作树、暂存标记、文件变化、提交历史；保持只读 |
| 本地模型 | Ollama 状态、已安装模型、容量、GPU/CPU 环境与能力状态 |
| 记忆 | 浏览、筛选、客户端搜索和写入现有记忆 API |
| 插件与工具 | 插件清单、权限、生命周期与后端能力状态；仅在 API 支持时开放启停 |

## 5. 视觉与组件系统

### 5.1 设计 Token

建议初始 Token：

| 用途 | 色值 |
|---|---|
| 页面背景 | `#0A0D10` |
| 导航/状态栏 | `#0F1419` |
| 主表面 | `#151B21` |
| 高层表面 | `#1B232B` |
| 边框 | `#2C353D` |
| 主文本 | `#EDF2F4` |
| 次文本 | `#8F9BA5` |
| 主操作 | `#42C8BD` |
| 正常 | `#56C984` |
| 警告 | `#E6AD54` |
| 错误 | `#EB6975` |

设计约束：

- 不使用霓虹光晕、装饰性渐变、背景色块或单一蓝紫配色。
- 圆角主要为 `4px`、`6px`、`8px`；不使用过度胶囊化的普通按钮。
- 正文采用系统无衬线字体栈，代码和技术标识采用等宽字体。
- 字号不随视口宽度缩放；紧凑工具区使用 `12px-14px`，页面标题使用 `20px-24px`。
- 图标按钮保持 `36px × 36px`，使用 Lucide 图标和 Tooltip，不再使用 `R`、`C` 等字母代替图标。
- 所有焦点状态、状态色和文本对比度满足 WCAG AA；遵守 `prefers-reduced-motion`。

### 5.2 Kobalte 使用范围

使用 `@kobalte/core` 提供交互语义与键盘行为：

- `Select`：模型选择与筛选。
- `Tooltip`：图标按钮和不可用能力说明。
- `Dialog` / `AlertDialog`：清空会话和其他需要确认的操作。
- `Toast`：写操作、刷新和重试的非阻塞反馈。
- `Tabs`：视图内部的紧凑切换，不承担一级导航。
- `Collapsible`：后台活动栏和移动端辅助信息。
- 项目自行封装 `Skeleton`，保持加载状态尺寸稳定。

项目在 `components/ui/` 中建立轻量封装，业务组件不直接复制 Kobalte 状态样式。

首期只交付已确认的“石墨精密”深色主题。颜色全部通过语义 Token 定义，为后续主题扩展保留边界，但本次不增加未经确认的主题切换控件。

### 5.3 依赖边界

新增运行时依赖限定为：

- `@kobalte/core`：可访问交互原语。
- `lucide-solid`：统一图标。
- `solid-markdown` 与 GFM 插件：不启用原始 HTML 的消息渲染。
- `systeminformation`：Express 侧跨平台系统采样。

新增开发依赖限定为 `@playwright/test`，用于桌面与移动端浏览器验证。除非实现时证明上述依赖无法满足已确认需求，不再引入第二套组件、图标、Markdown、系统采样或端到端测试库。

## 6. 前端架构

建议模块边界：

```text
frontend/src/
  app/
    navigation.ts
    resource-registry.ts
  components/
    layout/
      AppShell.tsx
      Sidebar.tsx
      Topbar.tsx
      StatusRail.tsx
      ActivityDock.tsx
    ui/
      Button.tsx
      IconButton.tsx
      ResourceState.tsx
      StatusIndicator.tsx
      ToastHost.tsx
  views/
    ChatView.tsx
    RuntimeView.tsx
    RepositoryView.tsx
    ModelsView.tsx
    MemoryView.tsx
    PluginsView.tsx
  services/
    jarvis-api.ts
    chat-stream.ts
  primitives/
    create-polling-resource.ts
  types/
    api.ts
  styles/
    tokens.css
    global.css
    components.css
```

设计规则：

- `App.tsx` 只负责顶层路由状态和应用外壳组合。
- 业务视图只通过 `jarvis-api.ts` 和资源注册表读取数据，不直接散落 `fetch`。
- 系统、Ollama 与 Git 摘要在顶栏、状态栏和详情视图间共享同一资源实例。
- `Chart.js` 仅在需要趋势图的视图中动态加载，避免主聊天视图承担完整图表包。
- 视图使用 Solid `lazy` 与 `Suspense` 分包，非当前视图不执行轮询。
- `GithubIntelligenceWidget`、`TokenUsageDashboardWidget` 及其 `innerHTML` 包装退出主 Dashboard；有价值内容改为普通 Solid 组件或保留在文档中。
- 聊天响应使用 `solid-markdown` 与 GFM 解析，不启用原始 HTML 渲染。

## 7. 类型化数据访问与资源状态

### 7.1 API 客户端

`jarvisApi` 按领域暴露 `chat`、`system`、`ollama`、`git`、`memory`、`plugins` 和 `events`。它负责：

- JSON 和错误响应解析。
- `AbortSignal` 透传。
- 成功数据归一化。
- 结构化错误码与用户可读消息映射。
- 后端能力缺失与普通空数据的区分。

业务组件不得依赖 Express、Python HTTPServer 或 FastAPI 的细微响应差异。

### 7.2 统一资源状态

所有读取型资源使用以下状态：

| 状态 | UI 行为 |
|---|---|
| `loading` | 首次读取，显示稳定尺寸 Skeleton |
| `ready` | 显示真实数据、来源和最近刷新时间 |
| `empty` | 请求成功但无记录，显示空状态与可执行下一步 |
| `stale` | 保留最后有效数据，并标注数据已过期 |
| `degraded` | 部分字段不可用，隐藏不可靠指标并说明原因 |
| `error` | 无有效数据，显示错误原因和重试入口 |

`createPollingResource` 提供统一轮询能力：

- 页面隐藏时暂停；恢复后立即刷新。
- 组件卸载和重新请求时取消旧请求。
- 自动失败采用有上限的指数退避；手动刷新立即执行。
- 临时失败保留最后一次有效数据。
- 同一资源只产生一个轮询源，避免多个组件重复请求。

## 8. 聊天与真实 Token 数据流

聊天流程：

1. 用户提交前校验模型、内容和当前流状态。
2. `chat-stream.ts` 创建 `AbortController`，向 Express SSE 端点提交历史消息。
3. 解析器兼容 LF、CRLF、跨 chunk 事件和结束时残余缓冲区。
4. UI 增量更新最后一条 assistant 消息，发送按钮切换为“停止”。
5. 用户停止或离开页面时取消连接，保留已生成内容。
6. 失败时保留已有内容，显示内联错误与“重试”操作。
7. Express 在 Ollama 最后一帧读取 `prompt_eval_count` 与 `eval_count`，更新进程内会话统计。

Token 端点返回最新调用、会话累计和时间序列样本。服务重启后累计清零是明确的首阶段行为；UI 标注“当前服务会话”，不表述为永久历史。

## 9. Express BFF 数据真实性改造

### 9.1 系统指标

引入成熟的 `systeminformation` 包：

- `currentLoad()` 获取真实 CPU 使用率。
- `mem()` 获取内存总量、已用量与使用率。
- `fsSize()` 获取跨平台磁盘容量和使用率。
- 图形设备信息采用缓存，避免高频昂贵探测。

某一指标读取失败时，端点返回其他可用字段和 `degraded` 元信息，不使用 `0` 伪装缺失值。

### 9.2 Python/FastAPI 能力桥接

Express 继续作为 Dashboard 的 BFF，通过可配置的 `JARVIS_CORE_API_URL` 访问 Python/FastAPI：

- 增加能力检测，区分 core API 在线、离线和未配置。
- 插件、记忆和事件端点在 core API 可用时代理真实响应。
- core API 不可用时返回结构化 `503` 与能力错误码，不返回误导性的空数组。
- 前端将该状态呈现为“后端能力未连接”，同时保持其他工作视图可用。

## 10. 错误处理与操作反馈

- 首次加载失败使用视图内错误状态；后台刷新失败使用 `stale` 状态，不清空已有数据。
- Toast 用于短暂操作结果；需要持续处理的问题保留在对应视图或状态栏。
- 禁用控件必须通过 Tooltip 或相邻文案说明原因。
- 清空对话等不可撤销操作使用 `AlertDialog`；刷新、停止生成等可撤销或低风险操作直接执行。
- 所有网络请求在组件卸载时取消，避免卸载后更新状态。
- 日志保留技术细节，UI 使用稳定错误码和可读中文消息；不得把堆栈直接显示给用户。

## 11. 性能与可访问性

- 六个工作视图按需加载；非当前视图停止轮询和图表更新。
- `Chart.js` 只在运行监控与需要趋势的详情中加载。
- 长事件与文件列表使用分页或 `content-visibility`，避免无限 DOM 增长。
- Solid 派生状态使用 `createMemo`，不通过 effect 复制可计算状态。
- 全局事件监听只注册一次并在卸载时清理；滚动监听使用 passive 模式。
- 导航、Select、Dialog、Toast 和工具提示支持键盘及读屏语义。
- 焦点不可被侧栏、抽屉或对话框丢失；关闭浮层后焦点返回触发控件。
- 桌面和移动端均不得出现文本截断导致的不可操作控件、重叠、横向滚动或滚动陷阱。

## 12. 测试策略

### 12.1 单元测试

- API 成功、错误、能力缺失和降级响应归一化。
- SSE 的 LF/CRLF、跨 chunk、结束残余、错误与取消。
- 轮询暂停、恢复、退避、手动刷新和最后有效数据保留。
- Token 最新值、累计值和时间序列更新。

### 12.2 组件测试

- 六个导航入口切换到正确视图。
- `loading`、`ready`、`empty`、`stale`、`degraded`、`error` 的视觉与可访问文本。
- 模型选择、停止生成、失败重试、清空确认和禁用原因。
- Kobalte 浮层的键盘操作、焦点返回和 Escape 行为。

### 12.3 服务端测试

- System 端点不再固定 CPU 为 `0`，并正确表达部分采样失败。
- SSE 转发保持既有协议，同时捕获 Ollama 最后一帧 usage。
- Token 端点不包含随机逻辑，累计与样本可预测。
- Core API 在线、离线、未配置三类能力响应。
- 现有健康、Git、Ollama、终端权限和静态文件行为回归。

### 12.4 浏览器 QA

使用 Playwright 验证：

- `1440 × 900` 桌面布局与 `390 × 844` 移动布局。
- 应用加载、一级导航、状态栏收起/展开、模型选择和聊天停止流程。
- 无框架错误覆盖层，无相关 console error/warning。
- 不存在组件重叠、文本溢出、横向滚动、焦点丢失和遮挡。
- 保留桌面与移动端截图作为本次验证证据，不提交临时截图或追踪文件。

## 13. 实施顺序

1. **基础设施**：依赖、设计 Token、UI primitives、类型和测试基线。
2. **数据层**：API 客户端、SSE 解析器、轮询资源、能力检测和真实指标。
3. **应用外壳**：导航、顶栏、状态栏、活动栏和响应式布局。
4. **工作视图**：先对话与运行监控，再仓库、模型、记忆、插件与工具。
5. **清理迁移**：移除主界面的旧占位 Widget 和 `innerHTML` 路径，更新相关测试。
6. **验证与文档**：单元、组件、服务端、浏览器 QA、README/SETUP 和迭代台账。

每一阶段保持可构建、可测试；不得以占位数据或无效按钮作为阶段完成证据。

## 14. 验收标准

1. 六个一级导航入口均渲染真实工作视图并支持键盘操作。
2. 桌面端、折叠导航和移动端布局均无重叠、遮挡和横向滚动。
3. UI 中不再使用 `R`、`C` 等字母模拟图标。
4. 主 Dashboard 不再通过 `innerHTML` 渲染 Widget。
5. CPU、磁盘和 Token 不再使用固定值、随机值或能力缺失的伪空数据。
6. Ollama 离线、Core API 未连接和轮询暂时失败均有明确且可恢复的 UI 状态。
7. 聊天支持流式生成、停止、错误保留与重试，并正确清理请求。
8. 前端测试、TypeScript 类型检查和生产构建通过。
9. Python 聚合测试、完整 discovery 和静态语法检查通过。
10. Playwright 在桌面与移动视口完成页面身份、非空、无错误覆盖层、console、截图和交互检查。

验证命令：

```powershell
.\venv\Scripts\python.exe tests/run_all.py
.\venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
.\venv\Scripts\python.exe -m compileall -q src tests

cd frontend
npm test -- --run
npm run typecheck
npm run build
npm run test:e2e
```
