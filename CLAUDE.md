# CLAUDE.md — 小奕 J.A.R.V.I.S. 项目上下文

**项目名称**：小奕 J.A.R.V.I.S. 自主演进引擎  
**项目路径**：`C:\GitHub\贾维斯\`  
**最后更新**：2026-07-08  

---

## 项目目标

将小奕从设计规范演进为具备全自主任务规划、多模态感知、动态工具链组装的 JARVIS 级本地智能系统。

## 核心协议

**单一源文档**：`JARVIS_核心指令.md` (v5.0)

所有十二阶段演进蓝图、安全协议、设计令牌、审计报告模板均从此文档引用。

## 当前项目结构

```
贾维斯/
├── JARVIS_核心指令.md          ← 单一源协议文档 (v5.0)
├── PROJECT_ANALYSIS.md         ← 项目扫描报告
├── jarvis-dashboard.html       ← JARVIS 监控面板 (Artifact)
├── skills/                     ← 8 个可部署技能
│   ├── jarvis-orchestrator/
│   ├── project-scanner/
│   ├── github-learner/
│   ├── security-auditor/
│   ├── ui-enforcer/
│   ├── audit-reporter/
│   ├── memory-keeper/
│   └── environment-probe/
├── src/                        ← 源代码目录（待 Phase 2 填充）
│   ├── core/
│   │   ├── kernel/             ← DI 容器、事件总线
│   │   └── brain/              ← 多 Agent 编排、记忆系统
│   ├── interface/
│   │   └── ui/                 ← 微前端模块化渲染
│   └── types/                  ← TypeScript 类型定义
├── config/                     ← 配置文件目录（待 Phase 2 填充）
│   └── design-tokens.ts        ← 设计令牌单一源
└── tests/                      ← 测试目录（待 Phase 12 填充）
```

## 十二阶段演进进度

| 阶段 | 名称 | 状态 |
|------|------|------|
| Phase 1 | 深度扫描与客观评估 | ✅ 完成 (PROJECT_ANALYSIS.md) |
| Phase 2 | 全局架构升级 | 🔄 进行中 (src/ 骨架已创建) |
| Phase 3 | GitHub 动态情报检索 | ⏸ 待启动 |
| Phase 4 | 组件萃取与本地化 | ⏸ 待启动 |
| Phase 5 | 本地环境动态探针 | ⏸ 待启动 |
| Phase 6 | 原子化组件安装 | ⏸ 待启动 |
| Phase 7 | Skill 生态市场 | ⏸ 待启动 |
| Phase 8 | Plugin 沙箱系统 | ⏸ 待启动 |
| Phase 9 | UI 赛博朋克重构 | ⏸ 待启动 |
| Phase 10 | Widget 引擎 | ⏸ 待启动 |
| Phase 11 | 小奕 AI 本格化进化 | ⏸ 待启动 |
| Phase 12 | 测试驱动自演进 | ⏸ 待启动 |

## 已部署的定时任务

- `jarvis-daily-scan` — 每日 10:07 自动扫描项目
- `jarvis-weekly-github` — 每周一 09:06 检索 GitHub 更新

## 已部署的 Artifacts

- `jarvis-dashboard` — J.A.R.V.I.S. 监控中心

## 已废弃文件

- `小奕_终极内核指令_JARVIS版.md` (v3.0) — 内容已合并至 v5.0
- `小奕_JARVIS协议_真实API映射版.md` (v4.0) — 内容已合并至 v5.0

## 设计令牌

见 `JARVIS_核心指令.md` 第四章。

## 技术栈（计划）

- **语言**：TypeScript (严格模式) + Python
- **前端**：Shadcn/ui + Tailwind CSS + Framer Motion
- **后端**：Node.js + Python
- **RAG/记忆**：Mem0 / LlamaIndex / LangChain
- **多 Agent**：AutoGen / CrewAI / LangGraph
- **测试**：Vitest / Playwright / Pytest

## 安全约束

- 所有代码变更必须通过静态 AST 审计
- 所有 Skill/Plugin 必须在沙箱中运行
- 回滚机制必须随时可用（使用 git stash 中间步骤）

---

*此文件由小奕 JARVIS 自主演进引擎 Phase 2 初始化。*
