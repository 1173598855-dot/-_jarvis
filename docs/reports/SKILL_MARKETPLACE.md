# Skill 生态市场 — 小奕 J.A.R.V.I.S.

**版本**：v1.0  
**更新时间**：2026-07-08

---

## 技能总览

共 **14 个已部署技能**，按功能分类如下：

---

## 🏗️ 核心编排（3）

| 技能 | 来源 | 描述 |
|------|------|------|
| jarvis-orchestrator | 自制 | 十二阶段全闭环 + 安全三防线 |
| project-scanner | 自制 | 项目深度扫描、四维评分、技术债清单 |
| github-learner | 自制 | GitHub 动态情报检索与部署 |

---

## 🔒 安全与审计（2）

| 技能 | 来源 | 描述 |
|------|------|------|
| security-auditor | 自制 | 静态代码审计、沙箱隔离、供应链安全 |
| audit-reporter | 自制 | 迭代审计报告生成、系统状态追踪 |

---

## 🧠 智能与记忆（2）

| 技能 | 来源 | 描述 |
|------|------|------|
| memory-keeper | 自制 | 上下文压缩、长期记忆维护、OCR |
| knowledge-graph-mapping | Graphify-Labs/graphify (79k ⭐) | 代码库知识图谱映射 |

---

## 💻 工程实践（5）

| 技能 | 来源 | 描述 |
|------|------|------|
| code-review | mattpocock/skills (160k ⭐) | 双轴代码评审（Standards + Spec） |
| tdd | mattpocock/skills (160k ⭐) | 测试驱动开发（红→绿循环） |
| diagnosing-bugs | mattpocock/skills (160k ⭐) | 故障诊断六阶段循环 |
| research | mattpocock/skills (160k ⭐) | 主源研究，Markdown 输出 |
| karpathy-guidelines | multica-ai (189k ⭐) | LLM 编码行为准则 |

---

## 🎨 UI 与设计（1）

| 技能 | 来源 | 描述 |
|------|------|------|
| ui-enforcer | 自制 | 设计令牌系统、Widget 组件开发 |

---

## 🌍 环境与工具（1）

| 技能 | 来源 | 描述 |
|------|------|------|
| environment-probe | 自制 | 本地环境扫描、AI 工具链探测 |

---

## 按运行时分类

### Python 运行时
- security-auditor（静态审计）
- memory-keeper（记忆压缩）
- environment-probe（环境探测）

### TypeScript/前端运行时
- ui-enforcer（设计令牌）
- knowledge-graph-mapping（图谱可视化）

### Agent 协议（Markdown）
- jarvis-orchestrator（核心指令）
- project-scanner（扫描协议）
- github-learner（检索协议）
- audit-reporter（报告协议）
- code-review（评审协议）
- tdd（测试协议）
- diagnosing-bugs（诊断协议）
- research（研究协议）
- karpathy-guidelines（编码准则）

---

## 按优先级分类

### P0（核心）
- jarvis-orchestrator
- project-scanner
- security-auditor

### P1（增强）
- code-review
- tdd
- diagnosing-bugs
- memory-keeper
- knowledge-graph-mapping

### P2（扩展）
- research
- ui-enforcer
- environment-probe
- github-learner
- audit-reporter
- karpathy-guidelines

---

## 技能调用方式

### 直接调用
```
Skill("skill-name", "args")
```

### 通过斜杠命令
```
/skill-name args
```

### 自动触发
某些技能可通过关键词自动触发：
- "代码评审" → code-review
- "测试驱动" → tdd
- "诊断 bug" → diagnosing-bugs
- "研究" → research
- "知识图谱" → knowledge-graph-mapping

---

## 新增技能流程

1. GitHub 搜索（github-learner）
2. 安全审计（security-auditor）
3. 部署（save_skill）
4. 分类（更新此文件）
5. 测试调用（mcp__skills__invoke_skill）

---

*此文件由 audit-reporter 自动维护*
