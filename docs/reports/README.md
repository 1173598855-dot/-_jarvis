# 项目报告索引

本目录保存项目分析、阶段交付和逐轮审计证据。运行状态以代码与当次测试结果为准，历史报告不等同于当前事实。

## 当前入口

| 文档 | 用途 |
|---|---|
| [PROJECT_ANALYSIS.md](PROJECT_ANALYSIS.md) | 2026-07-10 项目结构、风险与整理建议 |
| [AUDIT_REPORT_92.md](AUDIT_REPORT_92.md) | 最新一次清理、收敛与验证记录 |
| [PHASE6_INSTALLATION_REPORT.md](PHASE6_INSTALLATION_REPORT.md) | Phase 6 组件安装记录 |
| [GITHUB_LEARNING_REPORT.md](GITHUB_LEARNING_REPORT.md) | GitHub 技术情报与采纳决策 |
| [SKILL_MARKETPLACE.md](SKILL_MARKETPLACE.md) | 当前 19 个 Skill 的目录索引 |

## 审计台账

- 最新审计：Iteration 92。
- 当前滚动保存 10 份 `AUDIT_REPORT_N.md` 文件。
- 可用编号：`83-92`。
- 更早历史只保留在长期文档和 Git 历史中，不继续维护逐轮报告。
- 最新迭代摘要位于项目根目录 [CHANGELOG.md](../../CHANGELOG.md)。

## 维护规则

1. 新报告使用 `AUDIT_REPORT_<iteration>.md` 命名，并在 `CHANGELOG.md` 顶部登记。
2. 最新报告必须声明 `Iteration`、`Date`、`Status` 与验证命令。
3. 项目结构变化时更新 `PROJECT_ANALYSIS.md`，不要复制出新的“当前版”分析文件。
4. 临时测试报告使用 `.test-*.json`，由 `.gitignore` 排除。
5. 新增报告后删除窗口外最旧报告，始终只保留最近 10 份。
