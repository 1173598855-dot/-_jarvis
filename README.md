# 小奕 J.A.R.V.I.S. — 自主演进引擎

**版本**: v2.0  
**状态**: 🟢 运行中  
**架构评分**: 65/100

---

## 项目结构

```
贾维斯/
├── README.md                    ← 本文件
├── CLAUDE.md                    ← Claude Code 项目上下文
├── .gitignore
├── pyproject.toml               ← Python 项目配置
│
├── docs/                        ← 文档中心
│   ├── protocols/
│   │   └── JARVIS_核心指令.md    ← v5.0 单一源协议
│   ├── reports/                 ← 迭代审计报告
│   │   ├── PROJECT_ANALYSIS.md
│   │   ├── AUDIT_REPORT_1.md
│   │   ├── AUDIT_REPORT_2.md
│   │   ├── GITHUB_LEARNING_REPORT.md
│   │   └── LOCAL_ENVIRONMENT.md
│   └── deprecated/              ← 已废弃的历史文档
│       ├── 小奕_终极内核指令_JARVIS版.md
│       └── 小奕_JARVIS协议_真实API映射版.md
│
├── skills/                      ← Claude Skills（8 个）
│   ├── jarvis-orchestrator/
│   ├── project-scanner/
│   ├── github-learner/
│   ├── security-auditor/
│   ├── ui-enforcer/
│   ├── audit-reporter/
│   ├── memory-keeper/
│   └── environment-probe/
│
├── src/                         ← 源代码
│   ├── main.py                  ← REST API 服务器入口
│   ├── types/
│   │   └── index.ts             ← 30+ 接口定义
│   ├── core/
│   │   ├── kernel/              ← 核心层
│   │   │   ├── ollama_manager.py
│   │   │   ├── terminal_executor.py
│   │   │   ├── event_bus.py
│   │   │   └── plugin_sdk.py
│   │   └── brain/               ← 智能层
│   │       ├── context_compressor.py
│   │       ├── multi_agent_protocol.py
│   │       ├── ollama-monitor-widget.ts
│   │       └── system-monitor-widget.ts
│   └── widget-engine/
│       └── base-widget.ts
│
├── tests/                       ← 测试套件
│   └── run_all.py               ← 22 用例，100% 通过
│
├── plugins/                     ← 插件目录（待填充）
│
└── artifacts/                   ← Cowork Artifacts
    └── jarvis-dashboard.html    ← JARVIS 监控面板
```

## 快速启动

```bash
# 启动 REST API 服务器
python src/main.py

# 运行测试
python tests/run_all.py
```

## API 端点

服务器启动后访问 `http://localhost:8080`：

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/health` | GET | 健康检查 |
| `/api/system/stats` | GET | 系统统计 |
| `/api/ollama/status` | GET | Ollama 状态 |
| `/api/ollama/models` | GET | 已安装模型 |
| `/api/ollama/chat` | POST | 聊天请求 |
| `/api/terminal/execute` | POST | 终端命令执行 |
| `/api/plugins` | GET | 插件列表 |
| `/api/memory/entries` | GET | 记忆列表 |
| `/api/memory/store` | POST | 存储记忆 |
| `/api/events` | GET | 事件历史 |

## 组件来源

| 组件 | 萃取自 | 状态 |
|------|--------|------|
| Ollama 管理器 | AnythingLLM | ✅ |
| 终端执行器 | Open Interpreter | ✅ |
| 事件总线 | EventEmitter2 | ✅ |
| 多 Agent 协议 | AutoGen | ✅ |
| 上下文压缩器 | Mem0 | ✅ |
| Widget 引擎 | 自研 | ✅ |

## 迭代进度

| 迭代 | 架构评分 | 代码行数 | 测试用例 |
|------|---------|---------|---------|
| Iter 1 | 35 | 1,495 | 10 |
| Iter 2 | 65 | 2,500+ | 22 |

---

*由小奕 JARVIS 自主演进引擎维护*
