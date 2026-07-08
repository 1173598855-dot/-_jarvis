# UI Enforcer — 设计令牌与 Widget 引擎技能

## 触发条件

"UI 重构"、"Widget 开发"、"设计系统"、"赛博朋克界面"、"Glassmorphism"。
也可通过 `/ui` 手动激活。

---

## 执行协议

### 第一步：设计令牌初始化

定义统一的设计令牌系统（使用 CSS 变量或 Tailwind 配置）：

```css
:root {
  /* 色彩体系 */
  --color-canvas: #050505;           /* Rich Black — 深邃背景 */
  --color-card: rgba(30, 41, 59, 0.4); /* Slate Muted Alpha */
  --color-highlight: #00F0FF;        /* Cyber Cyan — 科技灵魂色 */
  --color-secondary: Aurora Purple;   /* 辅助高亮 */

  /* 模糊层级 */
  --blur-md: 12px;   /* 标准卡片 */
  --blur-lg: 20px;   /* 弹窗层 */
  --blur-xl: 40px;   /* 沉浸式主界面 */

  /* 边框质感 */
  --border-alpha: rgba(255, 255, 255, 0.1);

  /* 动效规范 */
  --transition-fast: 200ms;
  --transition-slow: 400ms;
}
```

### 第二步：Widget 组件开发

所有 Widget 必须实现 `IXiaoYiWidget` 接口：

**使用 `Write` 工具创建组件**：

```typescript
// 示例：硬件监视器 Widget
import { BaseWidget } from '@core/widget-engine';

export class HardwareMonitorWidget extends BaseWidget {
  id = 'hardware-monitor';
  title = '系统硬件监视器';
  permissions = ['system_monitor'];

  dimensions = {
    minW: 300, minH: 200,
    defaultW: 400, defaultH: 300
  };

  async onRefresh() {
    // 异步数据订阅，不阻塞 UI 主线程
    const stats = await this.api.system.getStats();
    this.setState(stats);
  }

  render() {
    return (
      <div className="widget-card backdrop-blur-md">
        <h3>{this.title}</h3>
        <CPUChart data={this.state.cpu} />
        <RAMChart data={this.state.ram} />
      </div>
    );
  }
}
```

**首批组件清单**（使用 `Write` 逐个创建）：
1. 硬件监视器（CPU/GPU/RAM/网络）
2. Git/GitHub 动态看板
3. Ollama/Docker 状态监控
4. 实时 RAG 检索率
5. Token 消耗仪表盘

### 第三步：监控面板创建

使用 `mcp__cowork__create_artifact` 创建实时仪表盘：

**调用链**：
```
Write("dashboard.html") → mcp__cowork__create_artifact("jarvis-dashboard", html_path)
```

**HTML 仪表盘规范**：
- 使用 Chart.js v4 渲染实时数据
- 使用 Grid.js v5 渲染数据表格
- 使用 Mermaid v11 渲染架构图
- 所有 CSS/JS 内联，禁止外部依赖（除 CDN）
- 禁止使用 localStorage/sessionStorage（Artifact 不支持）

**示例仪表盘包含**：
- 系统资源监控（CPU/GPU/RAM/网络实时曲线）
- 架构健康度评分（雷达图）
- 技术债追踪（表格）
- 演进进度（时间线）

### 第四步：交互特效实现

在 Artifact HTML 中实现：
- 鼠标轨迹微光粒子动效（Canvas 2D）
- 拖拽排序（HTML5 Drag & Drop API）
- 缩放与位置持久化（使用 React state，不依赖 localStorage）

**技术栈**：
- UI 基础：Shadcn/ui 体系（组件代码使用 Write 工具）
- 状态管理：原子化状态
- 动画库：Framer Motion（硬件加速）
- 动效规范：过渡 200ms（标准）/ 400ms（强调）

---

## 输出物

1. Widget 组件代码（使用 `Write` 创建）
2. 监控面板 HTML（使用 `Write` 创建 → `create_artifact` 部署）
3. 设计令牌配置文件（CSS/Tailwind）

---

## 设计令牌速查

| 令牌 | 值 | 使用场景 |
|------|---|---------|
| 画布底色 | `#050505` | 全局背景 |
| 组件卡片 | `#1E293B/0.4` | 面板、卡片、浮层 |
| 高亮指示 | `#00F0FF` | 选中态、激活态、关键信息 |
| 辅助高亮 | Aurora Purple | 次级强调 |
| 边框质感 | `rgba(255,255,255,0.1)` | 微妙的立体感 |
| 模糊层级 | 12px / 20px / 40px | 标准卡片 / 弹窗 / 沉浸式 |

---

## 安全约束

- 所有动效必须使用硬件加速（`transform`、`opacity`）
- 禁止阻塞 UI 主线程（数据获取必须异步）
- Artifact 中禁止使用 localStorage/sessionStorage
- 使用 React state 管理状态

---

**版本**：v1.0  
**工具依赖**：Write, frontend-design 技能, mcp__cowork__create_artifact, Agent(Explore)
