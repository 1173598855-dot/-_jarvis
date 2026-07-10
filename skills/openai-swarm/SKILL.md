# OpenAI Swarm — 轻量级多 Agent 编排框架

**来源**: [openai/swarm](https://github.com/openai/swarm)
**⭐ 21,772 Stars** | **语言**: Python | **许可证**: MIT | **更新**: 2026-07-08

---

## 核心能力

- **Agent 切换**：多个 Agent 之间智能路由
- **Handoff 机制**：Agent 之间无缝交接任务
- **极简设计**：核心代码 < 1000 行，易理解易扩展
- **OpenAI 官方出品**：与 OpenAI API 深度集成

## 可萃取能力（适配小奕）

| 能力 | 小奕对应路径 | 集成策略 |
|------|------------|---------|
| Agent Handoff 机制 | Phase 11 多 Agent 编排 | 借鉴任务交接逻辑 |
| 轻量级编排 | Phase 11 Task DAG 简化版 | 参考其极简设计哲学 |
| Agent 注册 + 路由 | `src/core/kernel/plugin_sdk.py` | 扩展 Skill 调用路由 |

## 安装方式

```bash
pip install git+https://github.com/openai/swarm.git
```

## 安全评估

- MIT 许可证 ✅
- OpenAI 官方出品 ✅
- 核心代码极简（~1000 行），审计成本低 ✅

## 下一步

1. Phase 11：借鉴 Handoff 机制实现小奕 Agent 路由
2. 作为 open-multi-agent 的轻量替代参考
3. 与 openai-agents-python 对比选型

---

**部署时间**: 2026-07-09 (Iter #17)
**状态**: ✅ 已记录（情报层），⏸ 待 Phase 11 集成
