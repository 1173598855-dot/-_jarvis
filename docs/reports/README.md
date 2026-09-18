# 项目报告索引

本目录保存当前分析、最近十轮审计和长期专题报告。当前状态以代码、配置和本次测试为准；审计报告只记录对应迭代的交付证据。

## 当前报告

顶层保留 Iteration 240-249，便于从一个固定窗口阅读最新证据。更早的
Iteration 230-239 已原样移入 [archive/](archive/)，没有从历史台账删除。

| 文档 | 说明 |
|---|---|
| [AUDIT_REPORT_249.md](AUDIT_REPORT_249.md) | Bounded provenance-aware memory search |
| [AUDIT_REPORT_248.md](AUDIT_REPORT_248.md) | Production Linux Terminal Worker kernel-enforcement evidence |
| [AUDIT_REPORT_247.md](AUDIT_REPORT_247.md) | Locale-independent discovery fixture diagnostics |
| [AUDIT_REPORT_246.md](AUDIT_REPORT_246.md) | Production Linux Plugin Runtime kernel-enforcement evidence |
| [AUDIT_REPORT_245.md](AUDIT_REPORT_245.md) | Linux Worker compatibility and real enforcement evidence |
| [AUDIT_REPORT_244.md](AUDIT_REPORT_244.md) | Direct allowlisted `network.get` egress and proxy isolation |
| [AUDIT_REPORT_243.md](AUDIT_REPORT_243.md) | macOS Seatbelt enforcement evidence and CI gate |
| [AUDIT_REPORT_242.md](AUDIT_REPORT_242.md) | Parent-owned OS isolation for the fixed Terminal Worker |
| [AUDIT_REPORT_241.md](AUDIT_REPORT_241.md) | Parent-owned macOS Seatbelt sandbox for Plugin Workers |
| [AUDIT_REPORT_240.md](AUDIT_REPORT_240.md) | Production Windows AppContainer launch for Plugin Workers |
| [PROJECT_ANALYSIS.md](PROJECT_ANALYSIS.md) | 当前架构、规模、评分、技术债和风险 |
| [PHASE6_INSTALLATION_REPORT.md](PHASE6_INSTALLATION_REPORT.md) | Phase 6 安装与环境报告 |
| [GITHUB_LEARNING_REPORT.md](GITHUB_LEARNING_REPORT.md) | GitHub 学习与项目实践报告 |
| [SKILL_MARKETPLACE.md](SKILL_MARKETPLACE.md) | 本地 19 个 Skill 的市场快照 |

## 维护规则

1. 每次迭代新增 `AUDIT_REPORT_<iteration>.md`，并同步更新 `CHANGELOG.md`。
2. 最新审计报告必须声明匹配的 `Iteration`、`Date` 和 `Status`。
3. 当前架构、规模和技术债统一更新到 `PROJECT_ANALYSIS.md`，不要从历史报告推断现状。
4. 临时测试产物和 Playwright 调试输出必须使用 `.test-*` 或由 `.gitignore` 明确忽略。
5. 超出顶层十轮窗口的报告移入 `archive/`，并保留原文件内容和导航说明。

完整迭代台账与每轮文件清单见 [CHANGELOG.md](../../CHANGELOG.md)。
