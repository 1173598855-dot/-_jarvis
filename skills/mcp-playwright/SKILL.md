# MCP Playwright — Playwright MCP Server

**来源**: [executeautomation/mcp-playwright](https://github.com/executeautomation/mcp-playwright)
**⭐ 5,574 Stars** | **语言**: TypeScript | **许可证**: MIT | **更新**: 2026-07-08

---

## 核心能力

- **Playwright + MCP 协议**：将 Playwright 浏览器自动化能力通过 MCP 暴露
- **浏览器 + API 自动化**：支持 Chrome/Firefox/Safari 自动化测试
- **Claude Desktop / Cursor 集成**：直接作为 MCP Server 运行

## 与小奕的集成路径

| 能力 | 小奕对应 | 集成策略 |
|------|---------|---------|
| Playwright 浏览器控制 | Phase 11 多模态感知 | 通过 MCP 协议接入前端 |
| API 自动化测试 | Phase 12 测试驱动 | 替代/增强现有 pytest 测试 |
| E2E 测试 | Phase 12 UI 性能测试 | FPS ≥ 60 验证 |

## 安装方式

```bash
git clone https://github.com/executeautomation/mcp-playwright.git mcp/mcp-playwright
cd mcp/mcp-playwright && npm install
```

## 安全评估

- MIT 许可证 ✅
- Playwright 官方背书 ✅
- 浏览器自动化天然沙箱，风险可控 ✅

## 下一步

1. Phase 7 注册为 MCP Server 到小奕 skill 生态
2. Phase 11 接入浏览器自动化能力
3. Phase 12 用于 E2E 测试（FPS 验证）

---

**部署时间**: 2026-07-09 (Iter #16)
**状态**: ✅ 已记录（情报层），⏸ 待 Phase 7/11/12 集成
