# Ruff — 极速 Python Linter + Formatter

**来源**: [astral-sh/ruff](https://github.com/astral-sh/ruff)
**⭐ 48,478 Stars** | **语言**: Rust | **许可证**: MIT | **更新**: 2026-07-08

---

## 核心能力

- **极速代码检查**：比 Flake8 快 10-100 倍（Rust 实现）
- **自动格式化**：替代 Black + isort，统一代码风格
- **多规则集**：PEP 8、flake8 规则、Pyflakes 规则全覆盖
- **零配置可用**：开箱即用，无需复杂配置

## 可萃取能力（适配小奕）

| 能力 | 小奕对应路径 | 集成策略 |
|------|------------|---------|
| Python 代码质量检查 | Phase 12 测试驱动 | 集成到 CI/CD 流程，每轮迭代自动检查 |
| 自动格式化 | `src/` 开发流程 | 统一代码风格，提升可维护性 |
| 快速静态分析 | security-auditor 技能增强 | 补充 AST 审计，加速安全检查 |

## 安装方式

```bash
pip install ruff
ruff check src/      # 检查代码
ruff format src/     # 格式化代码
```

## 安全评估

- MIT 许可证 ✅
- Astral 官方出品（UV、Ruff 同厂），代码质量高 ✅
- Rust 编写，内存安全 ✅
- 已用于生产环境（48k ⭐）✅

## 下一步

1. Phase 12：集成 ruff 到测试驱动流程
2. 每轮迭代后自动执行 `ruff check` + `ruff format`
3. 作为 security-auditor 的增强工具

---

**部署时间**: 2026-07-09 (Iter #17)
**状态**: ✅ 已记录（情报层），⏸ 待 Phase 12 集成
