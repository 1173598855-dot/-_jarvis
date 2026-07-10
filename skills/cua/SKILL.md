# CUA — Computer-Use Agent 开源基础设施

**来源**: [trycua/cua](https://github.com/trycua/cua)
**⭐ 19,462 Stars** | **语言**: HTML/JS | **许可证**: MIT | **更新**: 2026-07-08

---

## 核心能力

- **桌面自动化基础设施**：沙箱 + SDK + 评估基准
- **跨平台支持**：macOS、Linux、Windows 全支持
- **Agent 训练/评估**：标准化 benchmark 衡量 Computer Use 能力
- **沙箱隔离**：安全隔离的桌面操作环境

## 可萃取能力（适配小奕）

| 能力 | 小奕对应路径 | 集成策略 |
|------|------------|---------|
| 桌面沙箱设计 | Phase 8 Plugin 沙箱 | 借鉴沙箱架构设计 |
| Computer Use SDK | Phase 11 多模态感知 | 实现屏幕截图 → OCR → 操作决策 |
| Agent 评估基准 | Phase 12 测试驱动 | 建立小奕 Computer Use 测试基准 |

## 安装方式

```bash
git clone https://github.com/trycua/cua.git
```

## 安全评估

- MIT 许可证 ✅
- 沙箱设计天然隔离 ✅
- 19k ⭐，活跃开发 ✅

## 下一步

1. Phase 8：参考其沙箱架构设计小奕 Plugin 沙箱
2. Phase 11：接入 Computer Use 能力（屏幕截图 + 自动操作）
3. Phase 12：建立小奕 Computer Use 评估基准

---

**部署时间**: 2026-07-09 (Iter #17)
**状态**: ✅ 已记录（情报层），⏸ 待 Phase 8/11/12 集成
