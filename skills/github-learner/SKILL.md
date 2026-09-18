# GitHub Learner — 开源项目动态学习技能

## 触发条件

"学习 GitHub 项目"、"检索开源更新"、"萃取组件"、"研究 AutoGen/Mem0 等"。
也可通过 `/learn` 手动激活。

---

## 执行协议

### 第一步：动态情报检索

使用 `WebSearch` 检索目标项目的最新更新：

```
WebSearch("Open Interpreter latest updates 2026")
WebSearch("AutoGen multi-agent architecture 2026")
WebSearch("Mem0 memory management latest 2026")
WebSearch("AnythingLLM RAG integration 2026")
WebSearch("Bolt AI coding assistant 2026")
WebSearch("MCP servers protocol 2026")
```

使用 `web_fetch` 获取关键页面：
- GitHub Releases 页面
- GitHub README / ARCHITECTURE 文档
- 官方博客 / Changelog

### 第二步：架构分析

使用 `Agent`（subagent_type: "general-purpose"）进行深度分析：

提示词模板：
```
分析以下开源项目的架构设计，提取可借鉴的核心能力：

项目：[项目名]
GitHub：[URL]
最新更新：[从 WebSearch 结果中提取]

分析维度：
1. 架构设计模式（分层、模块化、依赖管理）
2. 多 Agent 协作逻辑（如适用）
3. Function Calling / 工具调用机制
4. 系统级自动化控制（Computer Use）
5. 代码组织与可扩展性

输出：可提取的能力清单 + 适配小奕架构的重构建议
```

### 第三步：组件萃取计划

基于分析结果，制定萃取计划：

| 目标能力 | 来源项目 | 萃取策略 | 小奕组件路径 |
|---------|---------|---------|------------|
| [能力名] | [项目名] | [解构/重构/封装策略] | `@core/xxx` |

**萃取原则**：
- ❌ 禁止直接复制代码
- ✅ 理解设计逻辑 → 用小奕架构重写 → 封装为标准组件

### 第四步：实现萃取

使用 `Write` 工具创建小奕原生组件：
- 组件代码（TypeScript/Python）
- 类型定义
- 测试用例

使用 `save_skill` 持久化为可复用技能（如适用）。

---

## 输出物

1. `docs/reports/GITHUB_LEARNING_REPORT.md` — 学习报告
2. 实际代码文件（使用 `Write` 创建）
3. 可复用技能（使用 `save_skill` 持久化）

---

## 监控目标项目

| 项目 | 关注重点 | 优先级 |
|-----|---------|-------|
| Open Interpreter | Computer Use、终端自动化 | ⭐⭐⭐ |
| AutoGen / CrewAI | 多 Agent 协作、任务分解 | ⭐⭐⭐ |
| Mem0 | 记忆管理、向量化存储 | ⭐⭐⭐ |
| AnythingLLM / Open WebUI | LLM 界面、RAG 集成 | ⭐⭐⭐ |
| Bolt / Cline | AI 编程、上下文感知 | ⭐⭐ |
| MCP Servers | 工具调用标准、协议规范 | ⭐⭐⭐ |

---

## 安全约束

- 仅学习和理解，不直接集成外部代码
- 所有萃取必须经过静态审计（调用 `Agent` 分析 AST）
- 高风险代码必须归档至 `RISK_COMPONENTS.log`

---

**版本**：v1.0  
**工具依赖**：WebSearch, web_fetch, Agent(general-purpose), Write, save_skill
