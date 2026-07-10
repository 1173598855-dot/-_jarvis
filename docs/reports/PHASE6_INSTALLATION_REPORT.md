# Phase 6 — 原子化组件安装报告

**日期**：2026-07-09　**状态**：✅ 完成

---

## 安装结果

| 组件 | 推荐工具 | 实际安装 | 版本 | 隔离策略 |
|------|---------|---------|------|---------|
| Python 包管理 | `uv` | uv | 0.11.19 | 专属 `.venv/` 虚拟环境 |
| npm 替代 | `pnpm` | 未安装 | — | 网络受限（GitHub/npm registry 不可达） |
| 代码检查 | `ruff` | ruff | 0.15.20 | uv tool 安装（独立环境） |
| Python 运行时 | CPython | CPython | 3.10.12 | 系统级 |
| 测试框架 | pytest | pytest | 9.1.1 | `.venv/` 内 |

## 已执行操作

1. **uv venv** — 在项目根目录创建 `.venv/`（CPython 3.10.12）
2. **uv pip install** — 安装项目依赖（requests, psutil）+ dev 依赖（pytest, pytest-cov）+ fastapi + httpx
3. **uv tool install ruff** — 安装 ruff 0.15.20 到用户工具目录（`.local/bin/ruff`）
4. **ruff check --fix** — 自动修复 12 处 import 排序问题（I001），0 剩余错误

## 验证结果

```
pytest:  788/788 passed (100%)
ruff:    0 errors (All checks passed!)
```

## 环境约束

- **pnpm**：网络不可达（npm registry + GitHub registry 均超时），未安装。项目当前使用 npm 已有 package.json，功能不受影响。
- **旧 venv/**（Windows 风格）：仍存在但不影响运行，`.venv/`（Linux uv 创建）为首选。

## 安全验证

| 检查项 | 结果 |
|--------|------|
| 虚拟环境隔离 | ✅ `.venv/` 独立于系统 Python |
| ruff 沙箱 | ✅ uv tool 独立环境 |
| 回滚可用 | ✅ 删除 `.venv/` 即可恢复 |
| 高危代码扫描 | ✅ 0 高危模式 |
