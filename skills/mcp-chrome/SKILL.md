# MCP Chrome — Chrome 浏览器 MCP Server

**来源**: [hangwin/mcp-chrome](https://github.com/hangwin/mcp-chrome)
**⭐ 12,060 Stars** | **语言**: TypeScript | **许可证**: MIT | **更新**: 2026-07-08

---

## 核心能力

- **Chrome 扩展式 MCP Server**：将 Chrome 浏览器功能暴露给 AI 助手
- **复杂浏览器自动化**：内容分析、语义搜索、页面交互
- **Claude Desktop 原生集成**：通过 MCP 协议直接调用

## 与小奕的集成路径

| 能力 | 小奕对应 | 集成策略 |
|------|---------|---------|
| Chrome 浏览器控制 | `frontend/src/components/ChatWidget.tsx` | 通过 MCP 协议扩展 ChatWidget |
| 页面内容分析 | Phase 11 多模态感知 | 截图 + OCR 理解页面内容 |
| 语义搜索 | Phase 11 RAG 增强 | 页面内容向量化检索 |

## 安装方式

```bash
# 方式1：直接 npm 安装
npm install -g @hangwin/mcp-chrome

# 方式2：clone 源码到 mcp/ 目录
git clone https://github.com/hangwin/mcp-chrome.git mcp/mcp-chrome
cd mcp/mcp-chrome && npm install
```

## 安全评估

- MIT 许可证 ✅
- Chrome 扩展权限模型天然沙箱化 ✅
- 需注意：扩展可访问浏览器全部数据，需在 Phase 8 沙箱中运行

## 下一步

1. Phase 8（Plugin 沙箱）建立后，将 mcp-chrome 安装到沙箱
2. Phase 11（AI 本格化）期间接入 ChatWidget，实现浏览器自动化

---

**部署时间**: 2026-07-09 (Iter #16)
**状态**: ✅ 已记录（情报层），⏸ 待 Phase 8/11 集成
