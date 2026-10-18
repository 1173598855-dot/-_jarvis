# AUDIT_REPORT_242.md

**Iteration**: #242
**Date**: 2026-09-05
**Status**: Complete

## 目标

为固定、只读的 `TerminalWorker` 接入与 Plugin Worker 一致的父端 OS
边界，同时保持终端协议、Linux 子端隔离、输出预算和生命周期语义不变。

## 需求与实现矩阵

| 要求 | 实现证据 | 验证 |
|---|---|---|
| 平台选择 | `os_isolation` 显式覆盖；注入 factory 可测试；真实 Windows/macOS 走平台 adapter；Linux 保持 direct path | `test_explicit_os_isolation_false_overrides_injected_platform_factory`、`test_injected_macos_factory_enables_isolation_for_a_non_macos_test_host`、unsupported-platform regression |
| 可信代码 staging | 复用 bounded、link-free `stage_worker_tree()`，每个 Worker 实例只 staging 一次 | `test_macos_isolated_launch_stages_once_and_uses_the_sandbox_root` |
| 单一 writable root | 平台 sandbox 提供 root；Worker 通过 `TerminalExecutor(sandbox_dir=...)` 复用，不创建嵌套临时目录 | `test_external_sandbox_root_is_used_without_executor_cleanup` 及 TerminalWorker staging/wiring tests |
| Windows ownership ordering | AppContainer 子进程挂起创建；先 `ProcessTreeContainment.attach`，再 `resume()` | `test_windows_isolated_launch_attaches_before_resume` |
| setup fail closed | staging、spawn、containment、resume 失败都返回失败结果，不调用 direct `subprocess.Popen` | setup/spawn/containment/resume no-fallback regressions |
| cleanup ownership | 未确认的 containment 保留；平台 sandbox close 失败保留并允许后续 `close()` 重试 | `test_platform_sandbox_cleanup_is_retained_for_retry`、failed release and resume regressions |
| wire/API compatibility | 请求字段、响应 schema、关联校验、bounded communication 和 audit shape 未改变 | `tests.test_terminal_worker`、aggregate API contract suite |

## 关键实现

- `TerminalWorker` 新增 `os_isolation`、`container_factory` 和
  `macos_sandbox_factory` 关键字选项。
- Windows 使用现有 `WindowsWorkerContainer`；macOS 使用现有
  `MacOSSandbox`。源码 staged 到平台代码根，工作目录为 staged `src/`。
- Worker 启动参数使用 `-S -u -m core.kernel.terminal_worker --worker`。
  `-S` 关闭环境 site startup，同时保留显式 staged `PYTHONPATH`；运行时探测
  证明 `-I` 会隐藏 staged import path，因此没有采用 `-I`。
- 平台 root 通过 `TMPDIR` 传递；Windows 同时设置 `TMP` 和 `TEMP`。
- 已启动但尚未完成 ownership 的隔离子进程不会降级为普通启动；cleanup
  只在 containment 已释放且进程已回收时关闭平台 sandbox。

## 自审结论

- 未修改 terminal request/response contract、command allowlist、timeout
  上限、bounded stdout/stderr collector 或审计字段。
- direct compatibility path 仅在 `os_isolation=False` 或 Linux 默认路径使用；
  隔离 setup 失败不会调用 direct spawn。
- `ProcessTreeContainment` 仍是 child tree 的最终 owner；`close()` 等待所有
  descendant 消失后才释放 containment，平台 sandbox 仍保留到此之后。
- 当前 Windows 主机可提供 AppContainer 的真实子进程证据；macOS 只能验证
  Seatbelt policy、staging、launch wiring 和 fail-closed contract，不能声称
  macOS kernel enforcement 已验证。Linux 现有 kernel boundary 未改变。

## 验证结果

| 命令 | 结果 |
|---|---|
| `python tests/run_all.py` | Total: 1142; passed: 1136; skipped: 6 |
| `python tests/run_all.py --timeout 1800 --json-report .test-i242-aggregate.json` | Total: 1142; passed: 1136; skipped: 6 |
| `python scripts/discover_tests.py --timeout 1800 --json-report .test-i242-discovery.json` | Total: 2111; passed: 2105; skipped: 6 |
| `python -m unittest tests.test_terminal_worker` | 42 passed |
| `python -m ruff check src tests scripts` | passed; zero findings |
| `python -m compileall -q src tests scripts` | passed |
| `cd frontend; npm test -- --run` | 151 passed |
| `cd frontend; npm run typecheck` | passed |
| `cd frontend; npm run build` | passed |
| `cd frontend; npm run test:e2e` | 7 passed; 1 conditional skip |
| `git diff --check` | passed |

## 残余边界

- macOS `sandbox-exec` 的实际 kernel enforcement 需要 macOS 主机或 CI runner。
- Linux 当前测试仍是决策逻辑/fail-closed 覆盖，不是本 Windows 主机上的真实
  Landlock 或 network namespace enforcement 证明。
- Windows/macOS platform adapters 的真实系统错误仍按 fail-closed 处理，未对
  不可用 launcher、权限、路径漂移或清理错误增加任何降级行为。

## 变更文件

- `src/core/kernel/terminal_worker.py`
- `src/core/kernel/terminal_executor.py`
- `tests/test_terminal_worker.py`
- `tests/test_terminal_executor_extended.py`
- `tests/test_terminal_executor_extended_v2.py`
- `AGENTS.md`
- `README.md`
- `CHANGELOG.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_242.md`
- `docs/superpowers/specs/2026-09-05-terminal-worker-os-isolation-design.md`
- `docs/superpowers/plans/2026-09-05-terminal-worker-os-isolation.md`
