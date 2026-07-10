# OpenBrowser — AI Agent 浏览器自动化工具包

**来源**: [ntegrals/openbrowser](https://github.com/ntegrals/openbrowser)
**⭐ 9,491 Stars** | **语言**: TypeScript | **许可证**: MIT | **更新**: 2026-07-08

---

## 核心能力

- **AI Agent 网页浏览**：自主导航、内容理解、数据提取
- **Playwright + Puppeteer 双引擎**：灵活选择底层驱动
- **沙箱环境**：安全隔离的浏览器会话
- **Claude 深度集成**：专门为 Claude 优化的浏览器工具

## 可萃取能力（适配小奕）

| 能力 | 小奕对应路径 | 集成策略 |
|------|------------|---------|
| Agent 浏览器导航 | Phase 11 多模态感知 | 实现 AI 驱动的网页浏览 |
| 内容理解 + 提取 | Phase 11 RAG 增强 | 页面 → 结构化数据 |
| 沙箱浏览器会话 | Phase 8 Plugin 沙箱 | 安全隔离的浏览器实例 |

## 集成优先级

**P1** — Phase 11（多模态感知）期间集成，作为小奕的"眼睛"。

## 安全评估

- MIT 许可证 ✅
- 沙箱设计天然隔离 ✅
- 代码量小（785 KB），审计成本低 ✅

## 下一步

1. Phase 8 沙箱系统就绪后，将 OpenBrowser 安装到沙箱
2. Phase 11 接入前端 ChatWidget，实现"让 AI 帮你浏览网页"

---

**部署时间**: 2026-07-09 (Iter #16)
**状态**: ✅ 已记录（情报层），⏸ 待 Phase 8/11 集成
