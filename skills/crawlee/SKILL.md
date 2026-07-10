# Crawlee — TypeScript 网页爬取与浏览器自动化库

**来源**: [apify/crawlee](https://github.com/apify/crawlee)
**⭐ 24,574 Stars** | **语言**: TypeScript | **许可证**: Apache-2.0 | **更新**: 2026-07-07

---

## 核心能力

- **多引擎爬取**：Playwright + Puppeteer + Cheerio + JSDOM
- **反爬虫对抗**：自动代理轮换 + 会话管理
- **AI 数据提取**：专为 LLM/RAG/GPT 数据准备设计
- **Headless/Headful 双模式**：灵活适配不同场景

## 可萃取能力（适配小奕）

| 能力 | 小奕对应路径 | 集成策略 |
|------|------------|---------|
| 爬取器基类 | `src/core/kernel/terminal_executor.py` | 借鉴其请求管理 + 重试逻辑 |
| 代理轮换 | Phase 11 网络工具 | 集成到小奕网络请求层 |
| 数据提取管道 | Phase 11 RAG 增强 | HTML → 结构化数据 → 向量化 |
| 会话管理 | `src/core/brain/context_compressor.py` | 借鉴其状态保持机制 |

## 集成优先级

**P1** — Phase 11（多模态感知 + RAG）期间集成 Crawlee 的数据提取能力。

## 安全评估

- Apache-2.0 许可证 ✅
- Apify 企业级出品，代码质量高 ✅
- 已用于生产环境（168,914 KB 代码库）✅

## 下一步

1. Phase 11 启动前，获取其 `packages/core/` 核心模块
2. 重点关注 `RequestQueue` + `Dataset` 的数据流设计
3. 在 Python 层用 httpx + BeautifulSoup 实现等效能力

---

**部署时间**: 2026-07-09 (Iter #16)
**状态**: ✅ 已记录（情报层），⏸ 待 Phase 11 集成
