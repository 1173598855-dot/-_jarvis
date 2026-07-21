# 项目报告索引

本目录维护当前项目分析、最近 10 轮迭代审计和仍有长期参考价值的专题报告。判断当前状态时，以代码、配置和本次测试结果为准；历史审计只记录当时的交付证据。

## 当前报告

| 文档 | 说明 |
|---|---|
| [PROJECT_ANALYSIS.md](PROJECT_ANALYSIS.md) | 2026-07-21 当前项目分析 |
| [AUDIT_REPORT_131.md](AUDIT_REPORT_131.md) | 原子恢复发布与角色任务生命周期加固 |
| [AUDIT_REPORT_130.md](AUDIT_REPORT_130.md) | 可终止异步角色任务生命周期与 OpenAPI 1.12 |
| [AUDIT_REPORT_129.md](AUDIT_REPORT_129.md) | Phase A 认证上下文连续性与启动恢复 |
| [AUDIT_REPORT_128.md](AUDIT_REPORT_128.md) | 默认拒绝的角色工具策略、Broker 与提示过滤 |
| [AUDIT_REPORT_127.md](AUDIT_REPORT_127.md) | 可恢复角色错误与 timeout 安全状态语义 |
| [AUDIT_REPORT_126.md](AUDIT_REPORT_126.md) | 生产 Ollama 角色执行与共享 Token 证据 |
| [AUDIT_REPORT_125.md](AUDIT_REPORT_125.md) | 三套服务适配器的角色路由对齐 |
| [AUDIT_REPORT_124.md](AUDIT_REPORT_124.md) | 编排器契约完整性与三适配器调度证据 |
| [AUDIT_REPORT_123.md](AUDIT_REPORT_123.md) | 三套服务适配器的共享编排器路由契约 |
| [AUDIT_REPORT_122.md](AUDIT_REPORT_122.md) | 确定性的 required-services 集成门禁 |
| [PHASE6_INSTALLATION_REPORT.md](PHASE6_INSTALLATION_REPORT.md) | Phase 6 安装与环境报告 |
| [GITHUB_LEARNING_REPORT.md](GITHUB_LEARNING_REPORT.md) | GitHub 学习与项目实践报告 |
| [SKILL_MARKETPLACE.md](SKILL_MARKETPLACE.md) | 本地 19 个 Skill 的市场快照 |

## 滚动策略

- 当前迭代为 131；仅保留最近 10 份 `AUDIT_REPORT_N.md`，当前范围为 122-131。
- 完整迭代台账与每轮文件清单见 [CHANGELOG.md](../../CHANGELOG.md)。

## 维护规则

1. 每次迭代新增 `AUDIT_REPORT_<iteration>.md`，并同步更新 `CHANGELOG.md`。
2. 最新审计报告必须声明匹配的 `Iteration`、`Date` 和 `Status`。
3. 当前架构、规模和技术债统一更新到 `PROJECT_ANALYSIS.md`，不要从历史报告推断现状。
4. 临时测试产物和 Playwright 调试输出必须使用 `.test-*` 或由 `.gitignore` 明确忽略。
5. 新增审计报告时删除超出滚动窗口的最旧报告，始终保持 10 份。
