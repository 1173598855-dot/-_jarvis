# AUDIT_REPORT_243.md

**Iteration**: #243
**Date**: 2026-09-05
**Status**: Complete

## 目标

补齐现有 macOS Seatbelt 边界的真实内核执行证据路径，同时保持生产
`MacOSSandbox` 策略、默认拒绝语义、staging 预算和 fail-closed 启动契约
不变。当前 Windows 主机不能执行 macOS `sandbox-exec`，因此本轮将真实
探针平台门禁为 macOS，并在 GitHub Actions 提供独立的 `macos-latest`
运行器。

## 范围与非目标

- 新增一个只在 `sys.platform == "darwin"` 且存在 `sandbox-exec` 时运行的
  unittest。
- 通过现有 `MacOSSandbox.create()`、`stage()`、`spawn()` 和
  `writable_root` 验证三项真实子进程结果。
- 保持父进程的 loopback listener 在子进程运行期间实际监听，避免用未占用
  端口冒充网络拒绝证据。
- 新增独立的 `macos-sandbox` CI job，使用哈希锁定的依赖安装。
- 不修改生产 Seatbelt profile，不新增依赖，不把 Windows skip 或注入式
  platform double 记录为 macOS kernel enforcement。

## 需求与实现矩阵

| 要求 | 实现证据 | 当前验证 |
|---|---|---|
| macOS 平台门禁 | 探针要求 `sys.platform == "darwin"` 和 `sandbox-exec` | Windows 主机明确 1 skipped |
| 真实文件拒绝 | 子进程读取授权根之外的临时文件 | macOS runner 执行时必须返回 `outside_read: denied` |
| 真实网络拒绝 | 父进程实际监听 loopback，子进程连接该端口 | macOS runner 执行时必须返回 `loopback: denied` |
| Worker 根可写 | 子进程在 `MacOSSandbox.writable_root` 创建文件 | macOS runner 执行时必须返回 `write: allowed` |
| 启动边界复用 | 通过既有 `stage()`/`spawn()`，不复制生产策略 | `test_worker_macos_sandbox` 5 passed |
| 超时与失败处理 | `communicate(timeout=5)`，staging/launch/非零退出/JSON 错误均失败 | focused unittest 通过；平台 skip 不伪造结果 |
| 持续集成证据路径 | `macos-sandbox` 使用 `macos-latest` 和两组 macOS 测试 | workflow contract 通过；待 macOS runner 提供非 skip 结果 |

## 关键变更

真实探针在临时目录中创建未授权文件和最小 Python 源文件，通过
`MacOSSandbox` staging 后以 `sandbox-exec` 启动。子进程只捕获受限操作的
`OSError`，输出排序后的 JSON；父进程在子进程结束前保持 listener，并对
输出、退出码、JSON 形状和三项精确结果做断言。

CI job 与其他 Ollama、前端和服务集成 job 解耦，先安装
`requirements.lock`，再以 `--no-deps --no-build-isolation` 安装本地项目，
最后运行 macOS sandbox contract 与 enforcement 测试。

## 自审结论

- 复用了生产 `MacOSSandbox` API 和现有 staging，不引入平行策略或直接
  `Popen` 绕过路径。
- 网络断言针对父进程真实监听端口；端口未监听、child 超时、staging 失败、
  launcher 失败、非零退出、错误 JSON 或错误访问结果都会使探针失败。
- 非 macOS 环境只记录 skip；本 Windows 主机的 skip 不构成 kernel
  enforcement 证据。
- 没有改动 Plugin/Terminal Worker 的生产启动路径、Broker 权限、协议或
  资源预算。
- `sandbox-exec` 的平台弃用状态和 macOS runner 可用性仍是后续运维边界；
  真实三项结果必须来自 macOS 非 skip 运行。

## 验证结果

| 命令 | 结果 |
|---|---|
| `python tests/run_all.py` | Total: 1142; passed: 1136; skipped: 6 |
| `python scripts/discover_tests.py --timeout 1800` | Total: 2112; passed: 2105; skipped: 7 |
| `python -m unittest tests.test_worker_macos_sandbox tests.test_macos_sandbox_enforcement` | 5 passed; 1 skipped on Windows |
| `python -m unittest tests.test_ci_workflow tests.test_readme tests.test_docs_setup tests.test_iteration_ledger` | 34 tests; 33 passed; 1 skipped |
| `python -m compileall -q src tests scripts` | passed |
| `python -m ruff check src tests scripts` | passed; zero findings |
| `git diff --check -- <Iteration 243 documentation and plan files>` | passed; full working-tree check is affected by pre-existing CRLF-only whitespace in `.github/workflows/ci.yml` |

## 残余边界

- 当前 Windows 工作树没有 macOS kernel enforcement 结果；必须读取
  `macos-sandbox` job 的非 skip 日志后，才能把三项结果升级为已实测证据。
- `sandbox-exec` 已被 macOS 标记为 deprecated，长期替代边界仍需独立设计。
- Linux namespace/Landlock 与 Windows AppContainer 的证据范围保持既有报告
  的描述，不因本轮 macOS 探针而扩大。

## 变更文件

- `.github/workflows/ci.yml`
- `tests/test_macos_sandbox_enforcement.py`
- `AGENTS.md`
- `README.md`
- `CHANGELOG.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_243.md`
- `docs/superpowers/specs/2026-09-05-macos-sandbox-enforcement-design.md`
- `docs/superpowers/plans/2026-09-05-macos-sandbox-enforcement.md`
