## Iteration #249 - 2026-09-09

**Protocol**: Bounded provenance-aware memory search
**Status**: Complete

### Achievements

- Ranked fixed read-only `memory_search` matches across bounded title, tag and
  body terms, using deterministic score/title/id ordering instead of file
  order.
- Added bounded `score`, `parent_id` and explicit `source_ids` provenance to
  each result without expanding permissions or write surfaces.
- Centered the redacted snippet on the first matching body position for long
  records, while preserving the existing 512-character result cap.
- Rejected blank or non-searchable queries before opening the memory store and
  retained all existing bounded read, symlink, redaction and Broker guards.

### Verification

- `python -m unittest tests.test_read_only_role_tools tests.test_role_tool_loop tests.test_role_worker -v`: 56 passed
- `python tests/run_all.py`: 1161 total (1150 passed, 11 skipped)
- `python scripts/discover_tests.py --timeout 1800`: 2135 total (2123 passed, 12 skipped)
- `python -m ruff check src tests scripts`: passed; zero findings
- `python -m compileall -q src tests scripts`: passed
- `git diff --check`: passed
- Frontend Vitest: 151 passed; Playwright: 7 passed and 1 desktop-conditional skip; typecheck and build passed

### Files Changed

- `src/core/brain/read_only_role_tools.py`
- `tests/test_read_only_role_tools.py`
- `AGENTS.md`
- `README.md`
- `CHANGELOG.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_249.md`

---

## Iteration #248 - 2026-09-07

**Protocol**: Production Linux Terminal Worker kernel-enforcement evidence
**Status**: Complete

### Achievements

- Added an opt-in real Linux probe that traverses production
  `TerminalWorker.execute()`, its request/response protocol, child
  `_worker_main()`, namespace/Landlock ordering, process containment and
  Worker-root cleanup without adding a production probe hook.
- Staged the trusted source tree through the existing bounded link-free copier,
  ran the outer driver as UID/GID 12345 when privileged, and proved baseline
  outside file, source-marker and live parent loopback access before the Worker
  boundary.
- Required outside read/write, source-root write and loopback denial while
  source reads and Worker-root writes remain available. Two test-only shim
  mutations independently disable filesystem or network isolation and require
  the corresponding access to become available, proving probe sensitivity.
- Reused the Plugin Runtime probe's 8 KiB-per-stream collector and ordered
  nested Worker-first process-tree reclamation. Wired all three modes into the
  aggregate suite and Ubuntu 22.04 `linux-sandbox` job.

### Verification

- `JARVIS_RUN_LINUX_TERMINAL_WORKER_ENFORCEMENT=1 python3 -m unittest tests.test_linux_terminal_worker_enforcement -v` on Ubuntu 24.04 WSL2 with UID/GID 12345: 3 passed
- `python tests/run_all.py`: 1158 total (1147 passed, 11 skipped)
- `python scripts/discover_tests.py --timeout 1800`: 2132 total (2120 passed, 12 skipped)
- Focused Terminal/isolation/aggregate/CI suite: 112 total (109 passed, 3 skipped)
- `python -m ruff check src tests scripts`: passed; zero findings
- `python -m compileall -q src tests scripts`: passed
- Frontend Vitest: 151 passed; typecheck and build passed; Playwright: 7 passed, 1 desktop-conditional skip

### Files Changed

- `.github/workflows/ci.yml`
- `tests/test_linux_terminal_worker_enforcement.py`
- `tests/test_ci_workflow.py`
- `tests/run_all.py`
- `tests/test_run_all_coverage.py`
- `AGENTS.md`
- `README.md`
- `CHANGELOG.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_248.md`
- `docs/superpowers/specs/2026-09-07-linux-terminal-worker-enforcement-design.md`
- `docs/superpowers/plans/2026-09-07-linux-terminal-worker-enforcement.md`

---

## Iteration #247 - 2026-09-07

**Protocol**: Locale-independent discovery fixture diagnostics
**Status**: Complete

### Achievements

- Reproduced the Windows `subprocess.run(text=True)` reader-thread failure
  under a forced parent ASCII decoder while the child emitted valid UTF-8.
- Locked the discovery end-to-end fixture to explicit UTF-8 decoding with
  `backslashreplace`, preserving valid Unicode exactly and retaining arbitrary
  output bytes as stable `\xNN` diagnostics.
- Added two platform-independent regressions without changing the production
  discovery runner, child environment defaults or project dependencies.

### Verification

- `python tests/run_all.py`: 1155 total (1147 passed, 8 skipped)
- `python scripts/discover_tests.py --timeout 1800`: 2128 total (2119 passed, 9 skipped)
- `python -m unittest tests.test_discover_tests_runner tests.test_run_all_coverage -v`: 66 passed
- Documentation contract suites: 27 passed
- `python -m ruff check src tests scripts`: passed; zero findings
- `python -m compileall -q src tests scripts`: passed
- Frontend Vitest: 151 passed; typecheck and build passed; Playwright: 7 passed, 1 desktop-conditional skip

### Files Changed

- `tests/test_discover_tests_runner.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `README.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/GITHUB_LEARNING_REPORT.md`
- `docs/reports/AUDIT_REPORT_247.md`
- `docs/superpowers/specs/2026-09-07-discovery-fixture-output-decoding-design.md`
- `docs/superpowers/plans/2026-09-07-discovery-fixture-output-decoding.md`

---

## Iteration #246 - 2026-09-07

**Protocol**: Production Linux Plugin Runtime kernel-enforcement evidence
**Status**: Complete

### Achievements

- Added an opt-in real Linux probe that exercises the production
  `SubprocessPluginRuntime` through start, load, activation, Broker event
  commit and confirmed close in a distinct Worker process.
- Proved an unprivileged driver can access an outside file and parent loopback
  listener before startup, plus a DAC-writable marker in the Plugin root. After
  namespace/Landlock setup Plugin code is denied the outside read/write,
  Plugin-root write and connection while only its Worker-owned root is writable.
- Reused the existing `event.emit` contract to return the bounded result and
  verified exact event provenance, lifecycle states, PID separation and
  temporary-root reclamation without adding a production hook or capability.
  The outer harness now drains each stream to an 8 KiB ceiling and reclaims the
  independent Worker groups before the driver group on timeout or overflow.
- Registered the honest opt-in skip in the aggregate suite and extended the
  Ubuntu 22.04 `linux-sandbox` job to run both primitive and production Runtime
  enforcement probes. Normalized mixed line endings in the already-modified
  Plugin Worker entrypoint after Ruff exposed them during self-review.

### Verification

- `python tests/run_all.py`: 1153 total (1145 passed, 8 skipped)
- `python scripts/discover_tests.py --timeout 1800`: 2126 total (2117 passed, 9 skipped)
- `JARVIS_RUN_LINUX_PLUGIN_RUNTIME_ENFORCEMENT=1 python3 -m unittest tests.test_linux_plugin_runtime_enforcement -v` on Ubuntu 24.04 WSL2 with UID/GID 12345: 4 passed
- Complete WSL2 `linux-sandbox` command with both opt-ins: 24 passed
- `python -m ruff check src tests scripts`: passed; zero findings
- `python -m compileall -q src tests scripts`: passed
- Frontend Vitest: 151 passed; typecheck and build passed; Playwright: 7 passed, 1 desktop-conditional skip

### Files Changed

- `.github/workflows/ci.yml`
- `src/runtime/plugin_worker.py`
- `tests/test_linux_plugin_runtime_enforcement.py`
- `tests/test_ci_workflow.py`
- `tests/run_all.py`
- `tests/test_run_all_coverage.py`
- `AGENTS.md`
- `README.md`
- `CHANGELOG.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_246.md`
- `docs/superpowers/specs/2026-09-06-linux-plugin-runtime-enforcement-design.md`
- `docs/superpowers/plans/2026-09-06-linux-plugin-runtime-enforcement.md`

---

## Iteration #245 - 2026-09-06

**Protocol**: Modern Linux Worker isolation compatibility and enforcement evidence
**Status**: Complete

### Achievements

- Preserved the privileged direct network namespace path and added an
  `EPERM`-only unprivileged fallback through a combined user/network namespace.
  The fallback maps the effective identity captured before namespace entry and
  fails closed on every syscall, mapping, partial-write, and cleanup error.
- Allowed Landlock ABI 3 and newer kernels to use the latest rights mask known
  to this implementation while retaining the real queried ABI in diagnostics.
- Added an opt-in real Linux child probe covering baseline access, outside
  read/write denial, real loopback denial, staged Plugin reads, and Worker-root
  writes. Added a dedicated Ubuntu 22.04 GitHub Actions job to run it.
- Strengthened self-review evidence by using UID/GID 12345 under root so the
  overflow-ID mapping bug cannot be hidden, and by reusing the bounded,
  link-free Worker staging primitive.

### Verification

- `python tests/run_all.py`: 1149 total (1142 passed, 7 skipped)
- `python scripts/discover_tests.py --timeout 1800`: 2121 total (2113 passed, 8 skipped)
- `JARVIS_RUN_LINUX_ISOLATION_ENFORCEMENT=1 python3 -m unittest tests.test_linux_worker_isolation_enforcement -v` on Ubuntu 24.04 WSL2/kernel 6.18 with UID/GID 12345: 1 passed
- `python -m ruff check src tests scripts`: passed; zero findings
- `python -m compileall -q src tests scripts`: passed
- Frontend Vitest: 151 passed; typecheck and build passed; Playwright: 7 passed, 1 desktop-conditional skip

### Files Changed

- `.github/workflows/ci.yml`
- `src/core/kernel/worker_filesystem_isolation.py`
- `src/core/kernel/worker_network_isolation.py`
- `tests/test_worker_filesystem_isolation.py`
- `tests/test_worker_network_isolation.py`
- `tests/test_linux_worker_isolation_enforcement.py`
- `tests/test_ci_workflow.py`
- `tests/run_all.py`
- `tests/test_run_all_coverage.py`
- `AGENTS.md`
- `README.md`
- `CHANGELOG.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_245.md`
- `docs/superpowers/specs/2026-09-06-linux-worker-enforcement-design.md`
- `docs/superpowers/plans/2026-09-06-linux-worker-enforcement.md`

---

## Iteration #244 - 2026-09-06

**Protocol**: Direct allowlisted egress for the read-only `network.get` Broker
**Status**: Complete

### Achievements

- Fixed a `network.get` classification defect where `requests.get()` could
  inherit ambient proxy and transport settings, causing an unreachable
  allowlisted target to return a successful proxy response.
- Switched the parent-owned fetch to a dedicated `requests.Session` with
  `trust_env = False`, preserving direct destination semantics and preventing
  host environment configuration from becoming an implicit egress path.
- Preserved per-hop host validation, redirect and response budgets, stable
  `network_get_denied` denials, and response/session cleanup on every path.

### Verification

- `python -m unittest tests.test_plugin_broker.TestPluginBrokerNetworkGet tests.test_subprocess_plugin_runtime.TestSubprocessPluginRuntime.test_network_get_broker_serves_parent_fetch tests.test_subprocess_plugin_runtime.TestSubprocessPluginRuntime.test_network_get_without_allowlist_is_a_stable_worker_denial tests.test_subprocess_plugin_runtime.TestSubprocessPluginRuntime.test_network_get_without_grant_is_a_stable_worker_denial`: 12 passed
- `python tests/run_all.py --timeout 1800 --json-report .test-autonomous-aggregate.json`: 1142 total (1136 passed, 6 skipped)
- `python scripts/discover_tests.py --timeout 1800 --json-report .test-autonomous-discovery.json`: 2112 total (2105 passed, 7 skipped)
- `python -m ruff check src tests scripts`: passed; zero findings
- `python -m compileall -q src tests scripts`: passed
- `cd frontend; npm test -- --run`: 151 passed
- `cd frontend; npm run typecheck`: passed
- `cd frontend; npm run build`: passed
- `cd frontend; npm run test:e2e`: 7 passed; 1 desktop-conditional skip

### Files Changed

- `src/core/kernel/plugin_broker.py`
- `docs/reports/AUDIT_REPORT_244.md`

---

## Iteration #243 - 2026-09-05

**Protocol**: macOS Seatbelt kernel-enforcement evidence
**Status**: Complete

### Achievements

- Added a macOS-only real-enforcement probe for the existing parent-owned
  `MacOSSandbox`. The probe stages a small source tree, launches it through
  `sandbox-exec`, and keeps a real parent-owned loopback listener open while
  the child checks its boundary.
- The probe requires all three outcomes: an ungranted file is unreadable,
  loopback access is denied, and the Worker-owned writable root remains
  writable. Non-macOS hosts explicitly skip this probe and do not produce
  macOS kernel-enforcement evidence.
- Added an independent `macos-sandbox` GitHub Actions job on
  `macos-latest`, using the locked dependency installation and the focused
  Seatbelt contract plus enforcement suites.
- Updated the current project guidance, analysis, report navigation and
  audit record without changing the production Seatbelt profile or adding a
  dependency.

### Verification

- `python tests/run_all.py`: 1142 total (1136 passed, 6 skipped)
- `python scripts/discover_tests.py --timeout 1800`: 2112 total (2105 passed, 7 skipped)
- `python -m unittest tests.test_worker_macos_sandbox tests.test_macos_sandbox_enforcement`: 5 passed, 1 skipped on Windows
- `python -m unittest tests.test_ci_workflow tests.test_readme tests.test_docs_setup tests.test_iteration_ledger`: 34 tests (33 passed, 1 skipped)
- `python -m ruff check src tests scripts`: passed; zero findings
- `python -m compileall -q src tests scripts`: passed
- `git diff --check -- <Iteration 243 documentation and plan files>`: passed; the full working-tree check still reports CRLF-only trailing whitespace from the pre-existing `.github/workflows/ci.yml` change.

### Files Changed

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

---

## Iteration #242 - 2026-09-05

**Protocol**: Parent-owned OS isolation for the fixed Terminal Worker
**Status**: Complete

### Achievements

- Wired the fixed, read-only `TerminalWorker` to the existing parent-owned
  Windows AppContainer and macOS Seatbelt adapters. Real Windows and macOS
  launches stage the trusted `src/` tree once, run from staged code, and expose
  only the platform sandbox's Worker-owned writable root.
- Preserved the fixed terminal request/response protocol, bounded output,
  process-tree containment, Linux namespace/Landlock path, and the public
  `sandbox_dir` compatibility surface. The Worker-side `TerminalExecutor`
  reuses the external platform root without creating a nested cleanup owner.
- Enforced `spawn -> containment -> resume` for suspended Windows children;
  setup, staging, containment, resume and cleanup failures fail closed and
  never fall back to ordinary `subprocess.Popen`. Explicit
  `os_isolation=False` remains the compatibility/test escape hatch.
- Added regression coverage for platform selection, staging reuse, writable
  root/environment/cwd wiring, containment-before-resume, no-fallback setup,
  containment/resume failure cleanup and retry-safe sandbox ownership. The
  Windows host provides real AppContainer evidence; macOS remains contract and
  policy evidence only until a macOS host or CI runner executes it.

### Verification

- `python tests/run_all.py`: 1142 total (1136 passed, 6 skipped)
- `python tests/run_all.py --timeout 1800 --json-report .test-i242-aggregate.json`: 1142 total (1136 passed, 6 skipped)
- `python scripts/discover_tests.py --timeout 1800 --json-report .test-i242-discovery.json`: 2111 total (2105 passed, 6 skipped)
- `python -m unittest tests.test_terminal_worker`: 42 passed
- `python -m ruff check src tests scripts`: passed; zero findings
- `python -m compileall -q src tests scripts`: passed
- `cd frontend; npm test -- --run`: 151 passed
- `cd frontend; npm run typecheck`: Passed
- `cd frontend; npm run build`: Passed
- `cd frontend; npm run test:e2e`: 7 passed; 1 conditional skip
- `git diff --check`: Passed

### Files Changed

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

---

## Iteration #241 - 2026-09-05

**Protocol**: Parent-owned macOS Seatbelt sandbox for Plugin Workers
**Status**: Complete

### Achievements

- Added a parent-owned macOS `sandbox-exec`/Seatbelt launch boundary to
  `SubprocessPluginRuntime`. Real macOS launches stage trusted Worker code and
  the Plugin into a private tree, apply a `(deny default)` profile, deny
  network access by omission, and expose only one Worker-owned writable root.
- Extracted bounded, link-free Worker-tree staging into a shared kernel helper;
  Windows continues to use the compatibility wrapper around that primitive.
- Kept the parent Broker bound to the validated real Plugin root while the
  child receives only staged paths. Missing launcher, profile, staging or
  launch failures fail closed without direct-spawn fallback; explicit
  `os_isolation=False` remains the compatibility/test escape hatch.
- Added macOS policy, path escaping, cleanup, staging, launcher failure and
  runtime-selection regressions. The Windows host records policy and
  fail-closed contract evidence only; it does not claim macOS kernel
  enforcement.

### Verification

- `python -m unittest tests.test_worker_macos_sandbox tests.test_subprocess_plugin_runtime`: 88 passed
- `python tests/run_all.py`: 1130 total (1124 passed, 6 skipped)
- `python tests/run_all.py --timeout 1800 --json-report .test-i241-aggregate.json`: 1130 total (1124 passed, 6 skipped)
- `python scripts/discover_tests.py --timeout 1800 --json-report .test-i241-discovery.json`: 2098 ran; OK (2092 passed, 6 skipped)
- `python -m ruff check src tests scripts`: passed; zero findings
- `python -m compileall -q src tests scripts`: passed
- `cd frontend; npm test -- --run`: 151 passed
- `cd frontend; npm run typecheck`: Passed
- `cd frontend; npm run build`: Passed
- `cd frontend; npm run test:e2e`: 7 passed; 1 conditional skip
- `git diff --check`: Passed

### Files Changed

- `src/adapters/subprocess_plugin_runtime.py`
- `src/core/kernel/worker_macos_sandbox.py`
- `src/core/kernel/worker_staging.py`
- `src/core/kernel/worker_windows_container.py`
- `tests/test_subprocess_plugin_runtime.py`
- `tests/test_worker_macos_sandbox.py`
- `tests/run_all.py`
- `AGENTS.md`
- `README.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_241.md`

---

## Iteration #240 - 2026-09-04

**Protocol**: Production Windows AppContainer launch for Plugin Workers
**Status**: Complete

### Achievements

- Wired the parent-owned Windows AppContainer boundary into
  `SubprocessPluginRuntime`. Real Windows `Popen` launches now stage trusted
  Worker sources and the Plugin into a private read-only tree, grant exactly one
  Worker-owned writable root, create the child suspended, attach process-tree
  containment, and resume only after ownership is established.
- Kept direct spawning available for explicit `os_isolation=False` and injected
  test factories, while real Windows setup failures remain fail-closed and never
  silently fall back to an ordinary Worker.
- Preserved the parent Broker's binding to the validated real Plugin root while
  the child receives only its staged Plugin root. The container's capability set
  remains empty; only staged code and the writable Worker root are granted.
- Closed the staged-validation failure path so an already-created container is
  released before the stable Worker start error escapes. Suspended thread handles
  are also closed on both resume success and setup failure.
- Added regression coverage for the SID/profile cleanup path, runtime selection,
  and container cleanup after staged Worker validation fails.

### Verification

- `python -m unittest tests.test_worker_windows_isolation tests.test_worker_windows_container`: 22 passed
- `python -m unittest tests.test_subprocess_plugin_runtime`: passed
- `python tests/run_all.py`: 1125 total (1119 passed, 6 skipped)
- `python tests/run_all.py --timeout 1800 --json-report .test-i240-aggregate-final.json`: 1125 total (1119 passed, 6 skipped)
- `python scripts/discover_tests.py --timeout 1800 --json-report .test-i240-discovery-final.json`: 2091 ran; OK (2085 passed, 6 skipped)
- `python -m ruff check src tests scripts`: passed; zero findings
- `python -m compileall -q src tests scripts`: passed
- frontend Vitest: 151 passed; typecheck/build passed; e2e 7 passed + 1 conditional skip
- `git diff --check`: passed

### Files Changed

- `src/adapters/subprocess_plugin_runtime.py`
- `src/core/kernel/worker_windows_container.py`
- `src/core/kernel/worker_windows_isolation.py`
- `tests/test_subprocess_plugin_runtime.py`
- `tests/test_worker_windows_container.py`
- `tests/test_worker_windows_isolation.py`
- `docs/reports/AUDIT_REPORT_240.md`

---

## Iteration #239 - 2026-09-04

**Protocol**: Honest isolation evidence and the first Windows Worker boundary
**Status**: Complete

### Achievements

- Corrected an overclaim this project had been repeating. `tests/test_worker_filesystem_isolation.py`
  and `tests/test_worker_network_isolation.py` inject `platform_name="linux"` with fake
  ctypes and carry no platform skip, so all 13 of their cases passed on this Windows host
  while no kernel ever denied anything. Only `tests/test_worker_resource_limits.py` has a
  real `skipIf(os.name == "nt")`. Iteration 238 copied "Worker filesystem isolation 8 passed"
  into the baseline without checking what it covered.
- Probed three Windows mechanisms against a real child before writing code.
  `CreateRestrictedToken` gives no network boundary. The AppContainer chain
  (`CreateAppContainerProfile` + `DeriveAppContainerSidFromAppContainerName` +
  `UpdateProcThreadAttribute(PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES)` +
  `CreateProcessW`) works here.
- Found that an AppContainer child cannot read the interpreter's own runtime, so it dies
  before `main()`. `icacls` on the system Python and the venv is denied without elevation,
  but both already grant `ALL APPLICATION PACKAGES` read/execute, so the boundary launches
  the base interpreter and grants only paths the parent owns.
- Added `src/core/kernel/worker_windows_isolation.py`: parent-side AppContainer profile
  creation or adoption, SID derivation and text conversion, `icacls` grants for
  caller-owned read paths plus exactly one writable Worker root, capability-free identity,
  and profile/SID reclamation on every failure path.
- Added 13 regressions: 11 contract cases plus two Windows-only real-enforcement cases that
  launch an actual child in an actual container.

### Verification

- `python -m unittest tests.test_worker_windows_isolation`: 13 passed
- mutation: forcing `EXTENDED_STARTUPINFO_PRESENT` off makes the enforcement case fail with
  `{'read': 'classified', 'write': 'ok', 'net': 'ok'}`, so the guard is not vacuous
- `python tests/run_all.py`: 1116 total (1110 passed, 6 skipped)
- `python scripts/discover_tests.py --timeout 1800`: 2079 ran, OK (skipped=6)
- `python -m ruff check src tests scripts`: passed
- `python -m compileall -q src tests scripts`: passed
- frontend Vitest: 151 passed; typecheck/build passed; e2e 7 passed + 1 skipped
- `git diff --check`: passed

### Files Changed

- `src/core/kernel/worker_windows_isolation.py`
- `tests/test_worker_windows_isolation.py`
- `tests/run_all.py`
- `tests/test_run_all_coverage.py`
- `AGENTS.md`
- `README.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/archive/AUDIT_REPORT_239.md`
- `docs/reports/AUDIT_REPORT_229.md` (removed from rolling window)

---

## Iteration #238 - 2026-09-04

**Protocol**: Owned integration ports and non-masking log cleanup
**Status**: Complete

### Achievements

- Closed the port-ownership gap in the required-services runner. `_free_port()` bound a
  port, closed the socket and returned the number, so nothing owned the port between
  allocation and the moment the service bound it. That window spanned two further
  allocations plus every earlier service start and health wait.
- Replaced it with `_PortReservation`/`_reserve_ports()`: the three ports stay bound
  simultaneously, so they are distinct by construction, and each reservation is released
  immediately before the child that binds it. `SO_EXCLUSIVEADDRUSE` is requested where it
  exists and `listen(1)` makes the reservation refuse a `SO_REUSEADDR` steal; the
  reservation never sets `SO_REUSEADDR` itself.
- Fixed a reproducible false CI failure in the same runner: a passing profile exited 2
  because `TemporaryDirectory` cleanup raised `WinError 32` on a service log handle that
  Windows had not yet released. Reproduced on 2 of 3 pre-change runs with the profile
  already reporting `"status": "passed"`.
- Cleanup now uses `mkdtemp` plus bounded `_remove_log_dir()` retries and reports a
  leftover path as a warning instead of overwriting the real exit code. Five consecutive
  post-fix runs exit 0 with no warning.
- Added 16 regressions covering reservation holding, release, idempotence, reuse refusal,
  bind failure, distinctness, mid-failure release, per-child release ordering and the four
  cleanup paths, and registered all four classes in the canonical aggregate suite.

### Verification

- `python -m unittest tests.test_ci_integration_resource_ownership`: 16 passed
- `python -m unittest tests.test_ci_integration_bounds tests.test_ci_integration_output_encoding tests.test_ci_integration_resource_ownership tests.test_discover_tests_runner`: 69 passed
- `python scripts/ci_local_integration.py --require-services --timeout 60 --overall-timeout 240`: exit 0 on 5 consecutive runs
- `python tests/run_all.py`: 1103 total (1097 passed, 6 skipped)
- `python scripts/discover_tests.py --timeout 1800`: 2065 ran, OK (skipped=6)
- `python -m ruff check src tests scripts`: passed
- `python -m compileall -q src tests scripts`: passed
- frontend Vitest: 151 passed; typecheck/build passed; e2e 7 passed + 1 skipped
- `git diff --check`: passed

### Files Changed

- `scripts/ci_local_integration.py`
- `tests/test_ci_integration_resource_ownership.py`
- `tests/run_all.py`
- `AGENTS.md`
- `README.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/archive/AUDIT_REPORT_238.md`
- `docs/reports/AUDIT_REPORT_228.md` (removed from rolling window)

---

## Iteration #237 - 2026-08-30

**Protocol**: Locale-safe bounded service diagnostics
**Status**: Complete

### Achievements

- Preserved readable service failure diagnostics when a Windows child emits locale-
  encoded bytes: strict UTF-8 decoding now falls back to the active locale and then
  to bounded replacement decoding.
- Set `PYTHONIOENCODING=utf-8` for Python services while retaining the existing
  unbuffered output setting.
- Added ten focused regressions for locale decoding, bounded tails, real child output,
  failure reporting and child environment construction.
- Registered the regressions in the canonical aggregate suite and synchronized the
  current iteration ledger.

### Verification

- `python -m unittest tests.test_ci_integration_output_encoding`: 10 passed
- `python tests/run_all.py`: 1087 total (1081 passed, 6 skipped)
- `python scripts/discover_tests.py --timeout 1800`: 2048 ran, OK (skipped=6), 2041 attributed
- `python -m ruff check src tests scripts`: passed
- `python -m compileall -q src tests scripts`: passed
- frontend Vitest: 151 passed; typecheck/build passed; e2e 7 passed + 1 skipped
- `git diff --check`: passed

### Files Changed

- `scripts/ci_local_integration.py`
- `tests/test_ci_integration_output_encoding.py`
- `tests/run_all.py`
- `AGENTS.md`
- `README.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/archive/AUDIT_REPORT_237.md`
- `docs/reports/AUDIT_REPORT_227.md` (removed from rolling window)

---

## Iteration #236 - 2026-08-30

**Protocol**: Bounded service integration with fail-fast health and tree reclamation
**Status**: Complete

### Achievements

- Closed the last verification step without a per-command deadline. `--timeout` was
  passed to the profile but never applied to the wait: a 60-second hang under
  `--timeout 3` ran the full 60.0 seconds, bounded only by the 45-minute job cap.
- Added `--overall-timeout` (default 300s). Each health wait and the profile take the
  smaller of their own budget and the remaining overall time, failing closed with the
  stage that ran out.
- Health waits now fail fast. A service that exited with code 3 previously burned 21.1
  seconds and lost the exit code; it is now reported immediately by name and code.
- Service output is captured to the managed temporary directory and a bounded 4 KiB tail
  is printed on failure, replacing `DEVNULL` silence.
- Timeout and shutdown paths reclaim the whole process tree; `_stop()` escalates when
  terminate is ignored.
- CI runs the step with `--overall-timeout 900`.

### Verification

- `python -m unittest tests.test_ci_integration_bounds`: 21 passed
- `python tests/run_all.py`: 1077 total (1071 passed, 6 skipped)
- `python scripts/discover_tests.py --timeout 1800`: 2038 ran, OK (skipped=6), 2031 attributed
- controls: no profile deadline -> 2 failures; no health fail-fast -> exit code lost
- `python -m ruff check src tests scripts`: passed
- `python -m compileall -q src tests scripts`: passed
- frontend Vitest: 151 passed; typecheck/build passed; e2e 7 passed + 1 skipped

### Files Changed

- `scripts/ci_local_integration.py`
- `tests/test_ci_integration_bounds.py`
- `tests/run_all.py`
- `tests/test_ci_workflow.py`
- `.github/workflows/ci.yml`
- `AGENTS.md`
- `README.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/archive/AUDIT_REPORT_236.md`
- `docs/reports/AUDIT_REPORT_226.md` (removed from rolling window)

---

## Iteration #235 - 2026-08-30

**Protocol**: Bounded unittest discovery with hang attribution and tree reclamation
**Status**: Complete

### Achievements

- Added `scripts/discover_tests.py`: full `unittest discover` now runs under a
  cooperative per-command deadline instead of relying on the 45-minute CI job cap.
- A timeout now names the wedged test. The runner forces unbuffered verbose output and
  tracks the started-but-unresolved case, reporting it with the last 20 outcomes.
- Timeout and output overflow reclaim the whole process tree (POSIX process group,
  Windows `taskkill /T`); killing only the direct child left grandchildren running.
- Each stream carries an independent 64 MiB budget and keeps draining after overflow so
  the child cannot block on a write before termination.
- Report records unittest's authoritative `Ran N tests` count alongside best-effort
  per-test attribution, which undercounts when a test writes newlines to stderr.
- CI runs the wrapper with `--timeout 1800` and uploads both Python JSON reports.

### Verification

- `python -m unittest tests.test_discover_tests_runner`: 22 passed
- `python tests/run_all.py`: 1056 total (1050 passed, 6 skipped)
- `python scripts/discover_tests.py --timeout 1800`: 2017 ran, OK (skipped=6), 2010 attributed
- control without `-v`: 4 regressions failed; control without tree kill: grandchild survived
- `python -m ruff check src tests scripts`: passed
- `python -m compileall -q src tests scripts`: passed
- frontend Vitest: 151 passed; typecheck/build passed; e2e 7 passed + 1 skipped

### Files Changed

- `scripts/discover_tests.py`
- `tests/test_discover_tests_runner.py`
- `tests/run_all.py`
- `tests/test_ci_workflow.py`
- `.github/workflows/ci.yml`
- `AGENTS.md`
- `README.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/archive/AUDIT_REPORT_235.md`
- `docs/reports/AUDIT_REPORT_225.md` (removed from rolling window)

---

## Iteration #234 - 2026-08-30

**Protocol**: Test runner CLI controls, truthful titles and hard timeout exit
**Status**: Complete

### Achievements

- Exposed `--smoke`, `--timeout SECONDS` and `--json-report PATH` through
  `tests/run_all.py`; previously the module entrypoint ignored all three.
- Made timeout worker threads daemonized and gated CLI timeout termination behind
  `abandon_on_timeout=True`, so a hung test cannot keep the CLI process alive.
- Replaced stale generic/Iteration 141 report titles with aggregate/smoke labels and
  exact class and test counts.
- Added 7 runner regressions; discovery now runs 1995 tests while canonical aggregate
  remains 1034.
- Updated CI with an 1800-second runner deadline, JSON artifact upload, and a
  45-minute Python contract job cap covering discovery and integration.

### Verification

- `python -m unittest tests.test_run_all_coverage`: 38 passed
- `python tests/run_all.py`: 1034 total (1028 passed, 6 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1995 total (1989 passed, 6 skipped)
- `python -m ruff check src tests scripts`: passed
- `python -m compileall -q src tests scripts`: passed
- frontend Vitest: 151 passed; typecheck/build passed; e2e 7 passed + 1 skipped

### Files Changed

- `.github/workflows/ci.yml`
- `tests/run_all.py`
- `tests/test_run_all_coverage.py`
- `AGENTS.md`
- `README.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/archive/AUDIT_REPORT_234.md`
- `docs/reports/AUDIT_REPORT_224.md` (removed from rolling window)

---

## Iteration #233 - 2026-08-29

**Protocol**: Truncation actually truncates and compression markers stop stacking
**Status**: Complete

### Achievements

- Fixed a correctness defect in `SemanticCompressor._truncate()`: it kept the
  leading 60% and trailing 40% of the body, which is the whole body plus a marker.
  Every "truncation" grew the record by 58 characters, raised its `token_count`,
  and turned `tokens_saved` negative.
- Added `_truncated_body()`, which bisects over kept characters to keep the largest
  head/tail pair whose token estimate fits `max_tokens`, and falls back to the
  marker alone when even that does not fit.
- Fixed unbounded title-marker stacking: five consolidations produced
  `planning [truncated] [truncated] [truncated] [truncated] [truncated]`. Added
  `_base_title()` and `_marked_title()` so marking strips existing markers first,
  making both transforms idempotent.
- Fixed silently broken duplicate detection: a transformed record no longer collided
  with its untransformed twin because the marker changed the title.
  `_merge_duplicates()` now keys on the base title, and a survivor that absorbed a
  differently marked twin drops back to the shared base title.
- Applied the same marker discipline to `LLMCompressor._llm_summarize()`,
  `_heuristic_summarize()` and `_merge_duplicates()`.
- Registered `TestSemanticCompressorBoundedTransforms` in the aggregate gate,
  raising it from 1018 to 1034 cases.

### Verification

- Bounded transform regressions: 16 passed
- Control run with real truncation reverted: 10 of 16 failed, file restored byte-identical
- Control run with base-title matching reverted: 1 of 16 failed, file restored byte-identical
- Context compressor suites (4 modules): 254 passed
- `python tests/run_all.py`: 1034 total (1028 passed, 6 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1988 total (1982 passed, 6 skipped)
- `cd frontend; npm test -- --run`: 151 passed
- `cd frontend; npm run typecheck`: passed
- `cd frontend; npm run build`: passed
- `cd frontend; npm run test:e2e`: 7 passed, 1 conditional skip
- `python -m compileall -q src tests scripts`: passed
- `python -m ruff check src tests scripts`: passed with zero findings
- `git diff --check`: passed

### Files Changed

- `src/core/brain/context_compressor.py`
- `tests/test_context_compressor.py`
- `tests/run_all.py`
- `AGENTS.md`
- `README.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/archive/AUDIT_REPORT_233.md`
- `docs/reports/AUDIT_REPORT_223.md` (removed from rolling window)

---

## Iteration #232 - 2026-08-29

**Protocol**: Duplicate merging keeps both bodies instead of dropping one
**Status**: Complete

### Achievements

- Fixed a data-loss defect: `SemanticCompressor._merge_duplicates()` was documented
  as merging duplicates but only selected the higher-`access_count` record and
  discarded the other whole. Iteration 231 made consolidation delete the dropped
  file, so that in-memory selection became permanent loss of the duplicate's body.
- Rewrote the fold so the survivor absorbs the other record's distinct content,
  unions tags, lifts `access_count`/`importance`/`last_accessed` to the maximum,
  lowers `created_at` to the minimum, recomputes `token_count`, and records
  absorbed ids in `metadata["merged_from"]`.
- Bounded absorption at 8,192 characters and 64 recorded ids. An over-budget merge
  keeps both records, so the bound never degrades into silent loss.
- Made absorption skip content the survivor already contains, so repeated
  consolidation is idempotent rather than accumulative.
- Reordered `_consolidate_unlocked()` to store survivors before deleting
  non-survivors, because a merged survivor now carries the absorbed body and the
  deletion must not be published before its replacement is durable.
- Registered `TestMemoryStoreLosslessMerge` in the aggregate gate, raising it from
  1006 to 1018 cases.

### Verification

- MemoryStore lossless merge regressions: 12 passed
- Control run with the lossless merge reverted: 10 of 12 failed, file restored byte-identical
- Control run with the store-before-delete ordering reverted: 2 of 12 failed, file restored byte-identical
- Context compressor suites (4 modules): 238 passed
- `python tests/run_all.py`: 1018 total (1012 passed, 6 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1972 total (1966 passed, 6 skipped)
- `cd frontend; npm test -- --run`: 151 passed
- `cd frontend; npm run typecheck`: passed
- `cd frontend; npm run build`: passed
- `cd frontend; npm run test:e2e`: 7 passed, 1 conditional skip
- `python -m compileall -q src tests scripts`: passed
- `python -m ruff check src tests scripts`: passed with zero findings
- `git diff --check`: passed

### Files Changed

- `src/core/brain/context_compressor.py`
- `tests/test_context_compressor.py`
- `tests/run_all.py`
- `AGENTS.md`
- `README.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/archive/AUDIT_REPORT_232.md`
- `docs/reports/AUDIT_REPORT_222.md` (removed from rolling window)

---

## Iteration #231 - 2026-08-29

**Protocol**: consolidate() applies the pruning and merging it reports
**Status**: Complete

### Achievements

- Fixed a correctness defect: `consolidate()` reported `pruned` and `merged` counts
  but never deleted those entry files or index rows, so the next `load()` returned
  the dropped records and the documented cleanup was a no-op.
- Extracted the journalled delete sequence into
  `_publish_entry_deletion_unlocked()` so probe deletion and consolidation share one
  journal/unlink/index-removal/rollback path.
- Added `_delete_entry_unlocked()`, a reusable in-transaction entry deletion that
  validates the publishable filename form, rejects non-regular and reparse targets,
  re-checks identity, and skips unreadable records without aborting a batch.
- Added `_bounded_legacy_records()` so each entry is paired with its real source
  path, because a record whose frontmatter type disagrees with its filename does
  not round-trip to the same name.
- Made consolidation delete every non-surviving record and report the real on-disk
  count as a new `removed` stat.
- Registered `TestMemoryStoreConsolidateRemoval` in the aggregate gate, raising it
  from 998 to 1006 cases.

### Verification

- MemoryStore consolidate removal regressions: 8 passed
- Control run with the removal loop reverted: 5 of 8 failed, file restored byte-identical
- Context compressor suites (4 modules): 218 passed
- Standard-library, FastAPI and role-tool suites: 381 passed
- `python tests/run_all.py`: 1006 total (1000 passed, 6 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1960 total (1954 passed, 6 skipped)
- `cd frontend; npm test -- --run`: 151 passed
- `cd frontend; npm run typecheck`: passed
- `cd frontend; npm run build`: passed
- `cd frontend; npm run test:e2e`: 7 passed, 1 conditional skip
- `python -m compileall -q src tests scripts`: passed
- `python -m ruff check src tests scripts`: passed with zero findings
- `git diff --check`: passed

### Files Changed

- `src/core/brain/context_compressor.py`
- `tests/test_context_compressor.py`
- `tests/run_all.py`
- `AGENTS.md`
- `README.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/archive/AUDIT_REPORT_231.md`
- `docs/reports/AUDIT_REPORT_221.md` (removed from rolling window)

---

## Iteration #230 - 2026-08-29

**Protocol**: Crash-consistent MemoryStore entry/index publication
**Status**: Complete

### Achievements

- Added a bounded durable intent journal so a writable MemoryStore mutation
  records the filename it is about to publish before the entry file changes.
- Added roll-forward reconciliation to every writable open and mutation: the
  index holds a row for the journalled filename exactly when that entry file
  exists and parses, making recovery idempotent.
- Skipped the recovery index write when the derived payload already matches,
  and shared one exact link-destination filter between probe deletion and
  reconciliation.
- Added bounded best-effort cleanup of temporaries left by a crashed atomic
  write, matched only against names that atomic write can produce.
- Consolidated the duplicated directory-fsync primitive: FileRunStateRepository
  now delegates to the shared `durable_directory` contract and only translates
  the error type.
- Registered the durable-directory and MemoryStore journal suites in the
  canonical aggregate gate, raising it from 967 to 998 cases.
- Ignored `.test-*.patch` and `.test-*.py` scratch artifacts.

### Verification

- MemoryStore and LLM compressor tests: 141 passed
- MemoryStore journal regressions: 19 passed
- Durable directory contract: 12 total (10 passed, 2 skipped)
- FileRunStateRepository: 38 total (35 passed, 3 skipped)
- Standard-library API tests: 263 passed
- FastAPI API tests: 109 passed
- `python tests/run_all.py`: 998 total (992 passed, 6 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1952 total (1946 passed, 6 skipped)
- `cd frontend; npm test -- --run`: 151 passed
- `cd frontend; npm run typecheck`: passed
- `cd frontend; npm run build`: passed
- `cd frontend; npm run test:e2e`: 7 passed, 1 conditional skip
- `python -m compileall -q src tests scripts`: passed
- `python -m ruff check src tests scripts`: passed with zero findings
- `git diff --check`: passed

### Files Changed

- `src/core/brain/context_compressor.py`
- `src/adapters/file_run_state_repository.py`
- `tests/test_context_compressor.py`
- `tests/test_file_run_state_repository.py`
- `tests/run_all.py`
- `.gitignore`
- `AGENTS.md`
- `README.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/archive/AUDIT_REPORT_230.md`
- `docs/reports/AUDIT_REPORT_220.md` (removed from rolling window)

---

## Iteration #229 - 2026-08-29

**Protocol**: Lossless MemoryStore v2 and bounded memory API surfaces
**Status**: Complete

### Achievements

- Added a lossless, strictly validated v2 MemoryStore serializer/parser with
  bounded `JSONEncoder.iterencode()` output and v1 read-only compatibility.
- Made the legacy footer scan linear for marker-rich bodies and documented
  the unavoidable v1 tag/marker ambiguities.
- Rejected writable memory-root links and unsafe entry/index targets, retained
  temporary-file cleanup after descriptor failures, and tightened probe type
  and escaped-label-aware exact-link deletion checks.
- Fixed index publication for re-storing an entry after its title changes by
  matching the entry filename while preserving same-title de-duplication.
- Added bounded read-only snapshots and response field limits to the stdlib
  and FastAPI memory listing endpoints, plus strict request tag/token types.
- Recorded the remaining cross-file crash, parent-directory fsync and
  non-cooperating same-user TOCTOU boundaries without overstating guarantees.

### Verification

- MemoryStore and LLM compressor tests: 114 passed
- Standard-library API tests: 263 passed
- FastAPI API tests: 109 passed
- `python tests/run_all.py`: 967 total (963 passed, 4 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1913 total (1909 passed, 4 skipped)
- `cd frontend; npm test -- --run`: 151 passed
- `cd frontend; npm run typecheck`: passed
- `cd frontend; npm run build`: passed
- `cd frontend; npm run test:e2e`: 7 passed, 1 conditional skip
- `python -m compileall -q src tests scripts`: passed
- `python -m ruff check src tests scripts`: passed with zero findings
- `git diff --check`: passed

### Files Changed

- `src/core/brain/context_compressor.py`
- `src/main.py`
- `src/main_fastapi.py`
- `tests/test_context_compressor.py`
- `tests/test_main.py`
- `tests/test_main_fastapi.py`
- `AGENTS.md`
- `README.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_229.md`
- `docs/reports/AUDIT_REPORT_219.md` (removed from rolling window)

---

## Iteration #228 - 2026-08-24

**Protocol**: Linux Terminal Worker OS boundary
**Status**: Complete

### Achievements

- Applied the existing Linux network namespace boundary to the fixed
  `TerminalWorker` before the child reads a request.
- Applied the existing Landlock boundary to the parent-owned temporary root;
  the root is writable only through the explicit `root_writable=True` call.
- Created the short-lived `TerminalExecutor` only after isolation, inside the
  declared root, so its temporary directory cleanup remains within the rule.
- Kept Windows and macOS explicitly unsupported for equivalent OS sandboxing;
  isolation failures remain fail-closed and the wire contract is unchanged.
- Added ordering, network-failure, filesystem-failure and root-writability
  regressions, plus a default-root read-only regression for the shared helper.

### Verification

- Terminal Worker, filesystem isolation and network isolation tests: 41 passed
- `python tests/run_all.py`: 930 total (926 passed, 4 skipped)
- `python -m compileall -q src tests scripts`: passed
- `python -m ruff check src tests scripts`: passed
- Full aggregate and discovery totals are recorded in `docs/reports/AUDIT_REPORT_228.md`.

### Files Changed

- `src/core/kernel/terminal_worker.py`
- `src/core/kernel/worker_filesystem_isolation.py`
- `tests/test_terminal_worker.py`
- `tests/test_worker_filesystem_isolation.py`
- `AGENTS.md`
- `README.md`
- `CHANGELOG.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_228.md`
- `docs/reports/AUDIT_REPORT_218.md` (removed from rolling window)

---

## Iteration #227 - 2026-08-24

**Protocol**: Close the POSIX `file.list` target identity race
**Status**: Complete

### Achievements

- Compared the directory identity captured during rooted `file.list` path
  validation with the descriptor opened for the POSIX scan before consuming
  entries, so replacement by another directory fails closed.
- Preserved descriptor-relative no-follow traversal, bounded entry scanning,
  post-scan identity checks and the cross-platform before/after fallback.
- Added a regression that exercises opened-directory identity drift and verifies
  the stable `file_list_denied` result with all owned descriptors closed.

### Verification

- `python -m unittest tests.test_plugin_broker.TestPluginBrokerFileList`: 9 passed
- `python -m unittest tests.test_plugin_broker`: 49 passed
- `python tests/run_all.py`: 925 total (921 passed, 4 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1863 total (1859 passed, 4 skipped)
- `python -m compileall -q src tests scripts`: passed
- `python -m ruff check src tests scripts`: passed
- `git diff --check`: passed

### Files Changed

- `src/core/kernel/plugin_broker.py`
- `tests/test_plugin_broker.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `README.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_217.md` (removed from rolling window)
- `docs/reports/AUDIT_REPORT_227.md`

---

## Iteration #226 - 2026-08-24

**Protocol**: Add Linux Plugin Worker Landlock filesystem isolation
**Status**: Complete

### Achievements

- Added a standard-library-only Landlock adapter for Linux Plugin Workers,
  with explicit supported ABI bounds through ABI 3, architecture syscall
  mapping, `no_new_privs` and fail-closed setup errors.
- Applied the ruleset before the Worker hello handshake. The verified plugin
  root and runtime/import paths are read-only; only the Worker-owned temporary
  directory receives bounded ordinary-file write access, with execute,
  device, socket, FIFO and symlink creation denied.
- Added no-follow directory opens, pre-open and descriptor identity checks,
  full descriptor cleanup and regressions for syscall order, ABI drift,
  setup failure, root omission, Worker ordering and non-Linux behavior.
- Moved the environment probe to the Worker temporary directory so existing
  lifecycle coverage matches the new read-only plugin-root contract.

### Verification

- `python -m unittest tests.test_worker_filesystem_isolation tests.test_plugin_worker_entrypoint`: 30 passed
- `python -m unittest tests.test_subprocess_plugin_runtime`: 57 passed
- `python tests/run_all.py`: 924 total (920 passed, 4 skipped)
- Full discovery, compile, Ruff and diff checks are recorded in
  `docs/reports/AUDIT_REPORT_226.md`.

### Files Changed

- `src/core/kernel/worker_filesystem_isolation.py`
- `src/runtime/plugin_worker.py`
- `tests/test_worker_filesystem_isolation.py`
- `tests/test_plugin_worker_entrypoint.py`
- `tests/test_subprocess_plugin_runtime.py`
- `tests/run_all.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `README.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_226.md`

---

## Iteration #225 - 2026-08-24

**Protocol**: Close the `file.read` rooted-open path race
**Status**: Complete

### Achievements

- Reworked the parent-owned `file.read` handler so POSIX reads open the
  validated root and every path component with descriptor-relative
  `O_NOFOLLOW` flags instead of reopening the resolved path after validation.
- Compared the pre-open target identity, opened descriptor identity, final
  descriptor state and final directory entry state; size growth, replacement,
  reparse points, non-regular files and short reads fail closed with the
  existing `file_read_denied` reason.
- Kept the bounded 1 MiB read and strict UTF-8 contract, retained the
  cross-platform open-before/after identity checks, and closed every owned
  descriptor on all paths.
- Added a regression that replaces the target between the path check and the
  open operation and verifies that the Broker denies the request.

### Verification

- `python -m unittest tests.test_plugin_broker.TestPluginBroker`: 31 passed
- `python tests/run_all.py`: 916 total (912 passed, 4 skipped)
- Full discovery, compile, Ruff and diff checks are recorded in
  `docs/reports/AUDIT_REPORT_225.md`.

### Files Changed

- `src/core/kernel/plugin_broker.py`
- `tests/test_plugin_broker.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `README.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_225.md`

---

## Iteration #224 - 2026-08-23

**Protocol**: Bounded read-only `file.list` Plugin Broker
**Status**: Complete

### Achievements

- Added `FILE_LIST_CAPABILITY`, reused the existing `file_read` Manifest
  permission and bound plugin-root fence, and introduced the stable
  `file_list_denied` reason with an exact 8,192 direct-entry budget.
- Added `PluginBroker.register_file_list_handler()` as an independent rooted
  registration gate. The handler accepts exactly `path`, rejects absolute or
  escaping paths, linked path components, non-directories, scan failures and
  metadata failures, and returns only direct children sorted by name with the
  exact `file`, `directory`, `link` or `other` types.
- The scan accepts an exact 8,192-entry boundary when the frozen response also
  fits the existing 65,536-byte Plugin Broker exchange budget; the first excess
  entry acts as a sentinel denial before a partial snapshot is returned.
- Added `XiaoYiPluginAPI.list_dir(path=".")` and registered the parent-owned
  handler in `PluginManager`; first-party grants remain unchanged and still
  include only `event.emit`.
- Added Broker, SDK, manager and real Worker regressions for authorization,
  rooted traversal, deterministic typing/order, the entry boundary, stable
  denials, SDK passthrough and granted/ungranted subprocess execution.

### Verification

- `python -m unittest tests.test_plugin_broker tests.test_plugin_sdk tests.test_subprocess_plugin_runtime tests.test_plugin_worker_entrypoint tests.test_plugin_worker_protocol tests.test_plugin_sdk_extended tests.test_plugin_sdk_extended_v2 tests.test_plugin_installation`: 330 passed
- `python tests/run_all.py`: 915 total (911 passed, 4 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1853 total (1849 passed, 4 skipped)
- `python -m compileall -q src tests scripts`: passed
- `python -m ruff check src tests scripts`: passed
- `git diff --check`: passed

### Files Changed

- `src/core/kernel/plugin_broker.py`
- `src/core/kernel/plugin_api.py`
- `src/core/kernel/plugin_sdk.py`
- `tests/test_plugin_broker.py`
- `tests/test_plugin_sdk.py`
- `tests/test_plugin_sdk_extended.py`
- `tests/test_subprocess_plugin_runtime.py`
- `tests/run_all.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `README.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_224.md`
- `docs/reports/AUDIT_REPORT_214.md`
- `docs/superpowers/specs/2026-08-23-plugin-file-list-design.md`
- `docs/superpowers/plans/2026-08-23-plugin-file-list.md`

---

## Iteration #223 - 2026-08-23

**Protocol**: Read-only `network.get` Plugin Broker with raw bounded HTTP egress
**Status**: Complete

### Achievements

- Added `NETWORK_GET_CAPABILITY`, `NETWORK_GET_PERMISSION` (`network`), the
  stable `network_get_denied` reason and the URL/header/body budgets (2,048
  UTF-8 URL bytes, 64 headers/8 KiB, 32 KiB UTF-8 body), then extended
  `MANIFEST_PERMISSION_BY_CAPABILITY` with `network.get -> network`.
- Added `PluginBroker.register_network_get_handler(hosts)`; the capability
  stays `capability_not_registered` until a service registers a non-empty
  host allowlist, and the handler accepts exactly `url`, rejects
  credentials, non-http(s) schemes, control characters, oversized URLs and
  hosts outside the allowlist, and follows at most three redirects while
  revalidating every hop against the same policy before returning one
  bounded JSON snapshot: status, a 64-entry/8 KiB header map and a strict
  UTF-8 body capped at 32 KiB.
- Network failures stay fail-closed: unreachable hosts, oversized bodies,
  malformed UTF-8, non-UTF-8 bodies and aborted streams all stabilize to
  the `network_get_denied` reason in the parent; unrelated exceptions
  remain parent-caught `handler_failed` denials, and the result still joins
  the existing per-session exchange budget with frozen stable results.
- `PluginManager` never registers a default allowlist: `network.get` stays
  `capability_not_registered` for every grant, first-party grants still
  cover only `event.emit`, and no default plugin grant includes
  `network.get`.
- Worker e2e evidence: a granted plugin calls `api.get_url` and receives
  the parent-fetched body; without registration or without a grant,
  activation fails with the stable `PLUGIN_BROKER_DENIED` worker error.

### Verification

- `python -m unittest tests.test_plugin_broker tests.test_plugin_sdk tests.test_subprocess_plugin_runtime tests.test_plugin_worker_entrypoint tests.test_plugin_worker_protocol tests.test_plugin_sdk_extended tests.test_plugin_sdk_extended_v2 tests.test_plugin_installation`: 316 passed
- `python tests/run_all.py`: 905 total (901 passed, 4 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1839 total (1835 passed, 4 skipped)
- `python -m ruff check src tests scripts`: passed

### Files Changed

- `src/core/kernel/plugin_broker.py`
- `src/core/kernel/plugin_api.py`
- `tests/plugin_network_fixture.py`
- `tests/test_plugin_broker.py`
- `tests/test_plugin_sdk.py`
- `tests/test_plugin_sdk_extended.py`
- `tests/test_subprocess_plugin_runtime.py`
- `tests/run_all.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `README.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_223.md`

---

## Iteration #222 - 2026-08-23

**Protocol**: Read-only `llm.call` Plugin Broker with a parent provider
**Status**: Complete

### Achievements

- Added `LLM_CALL_CAPABILITY`, `LLM_CALL_PERMISSION`, the stable
  `llm_call_denied` reason and the 32 KiB prompt budget, and extended
  `MANIFEST_PERMISSION_BY_CAPABILITY` with `llm.call -> llm_access`.
- Added `PluginBroker.register_llm_call_handler(provider)`; the capability
  stays `capability_not_registered` until a service supplies a callable
  provider, and the handler accepts exactly `prompt` plus `model`, rejects
  empty or oversized prompts (32 KiB UTF-8 bytes) and model names outside
  the 128-character whitelist, then evaluates the provider in the parent.
  Provider `llm_call_denied` denials and OSError/timeout/connection
  failures stabilize to `llm_call_denied`; other exceptions remain
  parent-caught `handler_failed` denials, and results still join the
  existing per-call exchange budget with frozen stable results.
- `PluginManager` never registers a default provider: release builds keep
  `llm.call` unregistered with `capability_not_registered`, and first-party
  grants still carry only `event.emit`; services opt in by calling
  `broker.register_llm_call_handler(...)` when they configure an
  Ollama-compatible client.
- Worker e2e evidence: granted plugins call `api.call_llm` and receive the
  parent provider result; without a provider or grant, activation fails with
  the stable `PLUGIN_BROKER_DENIED` worker error.

### Verification

- `python -m unittest tests.test_plugin_broker tests.test_plugin_sdk tests.test_subprocess_plugin_runtime tests.test_plugin_worker_entrypoint tests.test_plugin_worker_protocol tests.test_plugin_sdk_extended tests.test_plugin_sdk_extended_v2 tests.test_plugin_installation`: 300 passed
- `python tests/run_all.py`: 894 total (890 passed, 4 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1823 total (1819 passed, 4 skipped)
- `python -m ruff check src tests scripts`: passed

### Files Changed

- `src/core/kernel/plugin_broker.py`
- `tests/test_plugin_broker.py`
- `tests/test_plugin_sdk.py`
- `tests/test_subprocess_plugin_runtime.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `README.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_222.md`

---

## Iteration #221 - 2026-08-23

**Protocol**: Read-only `config.get` Plugin Broker
**Status**: Complete

### Achievements

- Added `CONFIG_GET_CAPABILITY`, `CONFIG_GET_PERMISSION`, the stable
  `config_get_denied` reason and a 64 KiB `config.json` read budget, and
  extended `MANIFEST_PERMISSION_BY_CAPABILITY` with `config.get -> system_config`.
- Added `PluginBroker.register_config_get_handler()` and a shared
  `_ROOTED_CAPABILITY_HANDLERS` dispatch so `file.read` and `config.get`
  share the same registered-flag, bound-root and stable-denial path.
- The config handler accepts only `key` plus optional `default`, validates
  the key against the 128-character whitelist, rereads the plugin's own
  `config.json` through a stat pre-check and one sentinel byte, and returns
  the requested JSON value or falls back to the provided default. Missing
  declaration, grant, registration or binding, invalid keys, links, invalid
  or non-object JSON, oversized files and bad UTF-8 all fail closed with
  either the existing denial or `config_get_denied`.
- `PluginManager` installs the handler for the stdlib HTTP, FastAPI and
  Express Core API proxy chains without changing first-party grants:
  first-party plugins are still granted only `event.emit`.

### Verification

- `python -m unittest tests.test_plugin_broker tests.test_plugin_sdk tests.test_subprocess_plugin_runtime tests.test_plugin_worker_entrypoint tests.test_plugin_worker_protocol tests.test_plugin_sdk_extended tests.test_plugin_sdk_extended_v2 tests.test_plugin_installation`: 292 passed
- `python tests/run_all.py`: 888 total (884 passed, 4 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1815 total (1811 passed, 4 skipped)
- `python -m ruff check src tests scripts`: passed

### Files Changed

- `src/core/kernel/plugin_broker.py`
- `src/core/kernel/plugin_sdk.py`
- `tests/test_plugin_broker.py`
- `tests/test_plugin_sdk.py`
- `tests/test_subprocess_plugin_runtime.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `README.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_221.md`

---

## Iteration #220 - 2026-08-23

**Protocol**: Read-only `file.read` Plugin Broker
**Status**: Complete

### Achievements

- Added `FILE_READ_CAPABILITY`, `FILE_READ_PERMISSION` and the
  `MANIFEST_PERMISSION_BY_CAPABILITY` entry `file.read -> file_read`.
- Added `PluginBroker.register_file_read_handler()` and
  `bind_file_read_root(plugin_id, root)`: the read fence is bound per plugin
  at Worker start to the plugin's own validated root.
- `SubprocessPluginRuntime.start()` binds the plugin root before launch; the
  handler rejects absolute paths, traversal, symlinks/reparse points and
  directories, and returns at most 1 MiB of UTF-8 content per read.
- Every rejected read uses the stable `file_read_denied` reason; unbound but
  enabled handlers, oversized files and invalid UTF-8 also fail closed.
- `PluginManager` installs the handler for the stdlib HTTP, FastAPI and
  Express Core API proxy chains. First-party plugins remain granted only
  `event.emit`; `file.read` is never granted by default.

### Verification

- `python -m unittest tests.test_plugin_broker tests.test_plugin_sdk.TestPluginManagerBrokerRegistration tests.test_plugin_sdk_extended tests.test_plugin_sdk_extended_v2 tests.test_subprocess_plugin_runtime.TestSubprocessPluginRuntime.test_file_read_broker_serves_files_inside_the_plugin_root tests.test_subprocess_plugin_runtime.TestSubprocessPluginRuntime.test_file_read_without_grant_is_a_stable_worker_denial`: 61 passed
- `python tests/run_all.py`: 881 total (877 passed, 4 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1806 total (1802 passed, 4 skipped)
- `python -m ruff check src tests scripts`: passed

### Files Changed

- `src/core/kernel/plugin_broker.py`
- `src/core/kernel/plugin_sdk.py`
- `src/adapters/subprocess_plugin_runtime.py`
- `tests/test_plugin_broker.py`
- `tests/test_plugin_sdk.py`
- `tests/test_subprocess_plugin_runtime.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_220.md`

---

## Iteration #219 - 2026-08-23

**Protocol**: Read-only `system.stats` Plugin Broker
**Status**: Complete

### Achievements

- Added `EVENT_EMIT_CAPABILITY`, `SYSTEM_STATS_CAPABILITY` and
  `SYSTEM_MONITOR_PERMISSION` constants and extended
  `MANIFEST_PERMISSION_BY_CAPABILITY` with `system.stats -> system_monitor`.
- Added `collect_system_stats_snapshot()`: bounded parent-owned CPU, memory,
  disk, network and process sampling with an ImportError zero-snapshot
  fallback and a deterministic 64-interface cap.
- Added `PluginBroker.register_system_stats_handler()` with strict empty-
  arguments validation.
- `PluginManager` installs the read-only handler for the stdlib HTTP, FastAPI
  and Express Core API proxy chains without changing first-party grants.
- Staged event assembly now only runs for `event.emit`, keeping non-event
  capabilities from being parsed as event frames.
- Kept declared/grant/registration denial semantics and budget enforcement.

### Verification

- `python -m unittest tests.test_plugin_broker tests.test_plugin_sdk tests.test_plugin_sdk_extended tests.test_subprocess_plugin_runtime tests.test_plugin_worker_entrypoint`: 233 passed
- `python tests/run_all.py`: 874 total (870 passed, 4 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1797 total (1793 passed, 4 skipped)
- `python -m ruff check src tests scripts`: passed

### Files Changed

- `src/core/kernel/plugin_broker.py`
- `src/core/kernel/plugin_sdk.py`
- `tests/test_plugin_broker.py`
- `tests/test_plugin_sdk.py`
- `tests/run_all.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_219.md`

---

## Iteration #218 - 2026-08-23

**Protocol**: Linux Plugin Worker network isolation
**Status**: Complete

### Achievements

- Added `core/kernel/worker_network_isolation.py` declaring one fixed Linux
  boundary: `unshare(CLONE_NEWNET)` before plugin code becomes importable.
- Ordered enforcement after resource budgets and before `sys.path`, imports,
  lifecycle input, and serving.
- Failed closed with worker exit code 2 for missing syscall support, syscall
  failure, or an unexpected errno.
- Added seven focused regressions across declaration, successful namespace
  entry, errno failure, missing symbol, non-Linux behavior, startup order, and
  fail-closed enforcement.
- Kept Windows/macOS network boundaries, filesystem isolation, and additional
  default-deny Brokers explicitly out of scope.

### Verification

- `python tests/run_all.py`: 868 total (864 passed, 4 skipped)
- `python -m unittest discover -s tests -p test_*.py`: 1791 total (1787 passed, 4 skipped)
- `python -m unittest discover -s tests -p test_*.py`: 1791 total (1787 passed, 4 skipped)
- `python -m unittest tests.test_worker_network_isolation`: 5 passed
- `python -m unittest tests.test_worker_network_isolation tests.test_plugin_worker_entrypoint tests.test_process_containment tests.test_subprocess_plugin_runtime`: 83 passed
- `python -m ruff check src tests scripts`: passed

### Files Changed

- `src/core/kernel/worker_network_isolation.py`
- `src/runtime/plugin_worker.py`
- `tests/test_worker_network_isolation.py`
- `tests/test_plugin_worker_entrypoint.py`
- `tests/run_all.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_218.md`

---

## Iteration #217 - 2026-08-21

**Protocol**: Worker OS-level resource budgets
**Status**: Complete

### Achievements

- Added `core/kernel/worker_resource_limits.py` with three fixed per-process
  Worker budgets: no core dumps, 64 MiB written file bytes, 256 open descriptors.
- Lowered both soft and hard POSIX bounds without ever raising an already
  stricter host limit, and skipped absent platform limits.
- Applied the budgets in `plugin_worker.py` before `sys.path` extension and
  serving, returning exit code 2 when enforcement fails.
- Applied 1 GiB per-process, 1 GiB per-job and 64 active-process limits to the
  Windows Job Object that already owned the Worker tree.
- Added 12 focused regressions across budget declaration, bound lowering,
  fail-closed enforcement, Job Object configuration and Worker startup order.
- Self-review removed `RLIMIT_NPROC`, which counts processes per real UID rather
  than per Worker tree; descendant count stays a Windows Job Object limit.

### Verification

- `python tests/run_all.py`: 854 total (850 passed, 4 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1777 total (1773 passed, 4 skipped)
- `python -m unittest tests.test_worker_resource_limits`: 7 total (6 passed, 1 skipped)
- `python -m unittest tests.test_process_containment tests.test_subprocess_plugin_runtime tests.test_plugin_installation tests.test_plugin_worker_entrypoint`: 82 passed
- `python -m compileall -q src tests scripts`: passed
- `python -m ruff check src tests scripts`: passed
- `git diff --check`: passed

### Files Changed

- `src/core/kernel/worker_resource_limits.py`
- `src/core/kernel/process_containment.py`
- `src/runtime/plugin_worker.py`
- `tests/test_worker_resource_limits.py`
- `tests/test_process_containment.py`
- `tests/test_plugin_worker_entrypoint.py`
- `tests/run_all.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_217.md`

---

## Iteration #216 - 2026-08-20

**Protocol**: Durable run-state directory entries
**Status**: Complete

### Achievements

- Added a no-follow `_fsync_directory()` helper so recovery renames, directory
  creation, and the archive unlink are durable, not just file contents.
- Flushed the parent directory after every atomic recovery-file replace, staged
  revision publication, recovery directory creation, and active-manifest unlink.
- Tolerated only unsupported-filesystem errnos and raised
  `RunStateIntegrityError` for every other directory flush failure.
- Added six focused regressions covering save, archive, unsupported
  filesystems, IO failure, Windows, and real POSIX flushes.

### Verification

- `python tests/run_all.py`: 842 total (839 passed, 3 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1765 total (1762 passed, 3 skipped)
- `python -m unittest tests.test_file_run_state_repository`: 38 total (35 passed, 3 skipped)
- `python -m compileall -q src tests scripts`: passed
- `python -m ruff check src tests scripts`: passed
- `git diff --check`: passed

### Files Changed

- `src/adapters/file_run_state_repository.py`
- `tests/test_file_run_state_repository.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_216.md`

---

## Iteration #215 - 2026-08-20

**Protocol**: Process-tree containment release confirmation
**Status**: Complete

### Achievements

- Required POSIX process groups and Windows Job Objects to be observed empty
  before `ProcessTreeContainment.close()` releases parent ownership.
- Kept containment attached when descendants remain active so termination can
  be retried and cleanup cannot be reported prematurely.
- Added focused POSIX and Windows Job Object regressions and validated the
  Plugin Worker lifecycle integration.

### Verification

- `python tests/run_all.py`: 836 total (834 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1759 total (1757 passed, 2 skipped)
- `python -m unittest tests.test_process_containment tests.test_subprocess_plugin_runtime`: 52 passed
- `python -m compileall -q src tests scripts`: passed
- `python -m ruff check src tests scripts`: passed
- `git diff --check`: passed

### Files Changed

- `src/core/kernel/process_containment.py`
- `tests/test_process_containment.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_215.md`

---

## Iteration #214 - 2026-08-19

**Protocol**: Ruff helper Python-module fallback
**Status**: Complete

### Achievements

- Made `scripts/ruff_check.py` prefer a PATH `ruff` executable while falling
  back to the current Python interpreter's `-m ruff` entry point.
- Kept version, lint, and format commands on the existing bounded process
  collector and 8 MiB per-stream output contract.
- Added a regression for an unactivated venv with Ruff available as a module.

### Verification

- `python tests/run_all.py`: 834 total (832 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1757 total (1755 passed, 2 skipped)
- `python -m unittest tests.test_ruff_check`: 5 passed
- `python -m compileall -q src tests scripts`: passed
- `python -m ruff check src tests scripts`: passed
- `python scripts/ruff_check.py --json`: Ruff detected; existing
  `src/runtime/plugin_worker.py` format finding reported

### Files Changed

- `scripts/ruff_check.py`
- `tests/test_ruff_check.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_214.md`
- `docs/superpowers/specs/2026-08-19-ruff-helper-module-fallback-design.md`
- `docs/superpowers/plans/2026-08-19-ruff-helper-module-fallback.md`

---

## Iteration #213 - 2026-08-19

**Protocol**: Bounded local Ruff helper subprocess output
**Status**: Complete

### Achievements

- Replaced unbounded `subprocess.run(..., capture_output=True)` calls in
  `scripts/ruff_check.py` with concurrent binary stdout/stderr readers.
- Capped each Ruff stream at 8 MiB of raw bytes, killed on the first overflow
  or timeout, and discarded partial output before JSON or diff parsing.
- Added four focused regressions covering successful output, independent stream
  overflow, child termination, and oversized version output.

### Verification

- `python tests/run_all.py`: 833 total (831 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1756 total (1754 passed, 2 skipped)
- `python -m unittest tests.test_ruff_check`: 4 passed
- `python -m compileall -q src tests scripts`: passed
- `python -m ruff check src tests scripts`: passed
- `python -m unittest tests.test_iteration_ledger tests.test_run_all_coverage`: passed

### Files Changed

- `scripts/ruff_check.py`
- `tests/test_ruff_check.py`
- `tests/run_all.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_213.md`
- `docs/superpowers/specs/2026-08-19-bounded-ruff-helper-output-design.md`
- `docs/superpowers/plans/2026-08-19-bounded-ruff-helper-output.md`

---

## Iteration #212 - 2026-08-18

**Protocol**: Bounded POSIX run-state cleanup directory entries
**Status**: Complete

### Achievements

- Replaced both descriptor-relative `tuple(os.listdir(fd))` snapshots in
  `FileRunStateRepository` cleanup with context-managed `os.scandir(fd)`.
- Bounded the revisions directory to 8,192 names and each flat recovery
  directory to the exact six known files; overflow retains all data and does
  not fail an otherwise committed save or archive operation.
- Added RED/GREEN regressions for scanner short-circuiting and zero partial
  deletion, retained every no-follow open and identity recheck, and verified
  the descriptor path with a native WSL POSIX smoke test.

### Verification

- `python tests/run_all.py`: 829 total (827 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1752 total (1750 passed, 2 skipped)
- `python -m unittest tests.test_file_run_state_repository`: 32 total (30 passed, 2 skipped)
- `cd frontend; npm test -- --run`: 149/149 passed
- `cd frontend; npm run typecheck`: passed
- `cd frontend; npm run build`: passed
- `$env:JARVIS_E2E_PORT='5174'; npm run test:e2e`: 7 passed, 1 conditional skip
- WSL native POSIX descriptor scan, compileall, Ruff, required-services local
  integration, ledger, and `git diff --check`: passed

### Files Changed

- `src/adapters/file_run_state_repository.py`
- `tests/test_file_run_state_repository.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_212.md`
- `docs/reports/AUDIT_REPORT_202.md` (removed from rolling window)
- `docs/superpowers/specs/2026-08-18-bounded-run-state-cleanup-entries-design.md`
- `docs/superpowers/plans/2026-08-18-bounded-run-state-cleanup-entries.md`

---

## Iteration #211 - 2026-08-18

**Protocol**: Bounded local Ollama fixture request bodies
**Status**: Complete

### Achievements

- Added a 32 KiB declared request-body budget to
  `scripts/local_ollama_fixture.py` before reading from the socket.
- Normalized invalid lengths, missing streams, non-byte bodies and non-object
  JSON into the existing deterministic 400 `invalid request` response.
- Added a RED/GREEN regression proving an oversized declaration is rejected
  without touching the request stream; valid tool round trips remain unchanged.

### Verification

- `python tests/run_all.py`: 826 total (824 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1749 total (1747 passed, 2 skipped)
- `python -m unittest tests.test_local_integration_runner`: 5 passed
- `cd frontend; npm test -- --run`: 149/149 passed
- `cd frontend; npm run typecheck`: passed
- `cd frontend; npm run build`: passed
- `$env:JARVIS_E2E_PORT='5174'; npm run test:e2e`: 7 passed, 1 conditional skip
- Compileall, Ruff, required-services local integration, ledger, and
  `git diff --check`: passed

### Files Changed

- `scripts/local_ollama_fixture.py`
- `tests/test_local_integration_runner.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_211.md`
- `docs/superpowers/specs/2026-08-18-bounded-local-ollama-fixture-body-design.md`
- `docs/superpowers/plans/2026-08-18-bounded-local-ollama-fixture-body.md`

---

## Iteration #210 - 2026-08-18

**Protocol**: Bounded GitWorkspace child-process output
**Status**: Complete

### Achievements

- Replaced unbounded `subprocess.run(capture_output=True)` in
  `GitWorkspaceInspector` with concurrent bounded stdout/stderr readers.
- Applied an 8 MiB raw-byte limit per stream, killed the child at the first
  overflow, and preserved the existing 10-second timeout, non-zero exit and
  sanitized environment contracts.
- Added a real-process fake regression proving overflow is rejected before Git
  porcelain output reaches parsing; migrated fixed-command tests to the bounded
  Popen contract.

### Verification

- `python tests/run_all.py`: 825 total (823 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1748 total (1746 passed, 2 skipped)
- `python -m unittest tests.test_run_lifecycle.TestGitWorkspaceInspector`: 3 passed
- `cd frontend; npm test -- --run`: 149/149 passed
- `cd frontend; npm run typecheck`: passed
- `cd frontend; npm run build`: passed
- `$env:JARVIS_E2E_PORT='5174'; npm run test:e2e`: 7 passed, 1 conditional skip
- Compileall, Ruff, required-services local integration, ledger, and
  `git diff --check`: passed

### Files Changed

- `src/adapters/git_workspace.py`
- `tests/test_run_lifecycle.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_210.md`
- `docs/superpowers/specs/2026-08-18-bounded-git-workspace-output-design.md`
- `docs/superpowers/plans/2026-08-18-bounded-git-workspace-output.md`

---

## Iteration #209 - 2026-08-18

**Protocol**: Bounded writable MemoryStore legacy directory entries
**Status**: Complete

### Achievements

- Added a fixed 8,192-entry direct-directory budget to writable
  `MemoryStore._load_legacy()` using a context-managed `os.scandir()` snapshot.
- Rejected the first excess entry before retaining or parsing any candidate and
  returned an empty fail-closed snapshot; exact-budget directories remain
  readable in deterministic name order.
- Preserved the existing `MEMORY.md` exclusion, regular-file and reparse-point
  checks, per-entry byte budget, metadata isolation and consolidation behavior.
- Added exact-budget, overflow-without-partial-results and scanner short-circuit
  regressions with a RED/GREEN TDD cycle.

### Verification

- `python tests/run_all.py`: 824 total (822 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1747 total (1745 passed, 2 skipped)
- `python -m unittest tests.test_context_compressor tests.test_context_compressor_llm`: 83 passed
- `cd frontend; npm test -- --run`: 149/149 passed
- `cd frontend; npm run typecheck`: passed
- `cd frontend; npm run build`: passed
- `$env:JARVIS_E2E_PORT='5174'; npm run test:e2e`: 7 passed, 1 conditional skip
- Compileall, Ruff, required-services local integration, ledger, and
  `git diff --check`: passed

### Files Changed

- `src/core/brain/context_compressor.py`
- `tests/test_context_compressor.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_209.md`
- `docs/superpowers/specs/2026-08-18-bounded-memory-store-legacy-directory-design.md`
- `docs/superpowers/plans/2026-08-18-bounded-memory-store-legacy-directory.md`

---

## Iteration #208 - 2026-08-18

**Protocol**: Bounded run-state recovery directory entries
**Status**: Complete

### Achievements

- Added a strict 8,192-entry `os.scandir()` budget for unpublished run-state
  revision candidates, with smaller two-entry run-root and six-file published
  revision limits.
- Rejected the first excess entry before retaining it, preserving fail-closed
  behavior for incomplete recovery data and preventing unbounded `iterdir()`
  materialization.
- Kept authenticated file-byte budgets, archive markers, valid retry recovery,
  descriptor-relative cleanup and existing revision semantics unchanged.
- Added fixed-budget, overflow-rejection and scanner short-circuit regressions.

### Verification

- `python tests/run_all.py`: 821 total (819 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1744 total (1742 passed, 2 skipped)
- `python -m unittest tests.test_file_run_state_repository`: 29 tests (27 passed, 2 skipped)
- `cd frontend; npm test -- --run`: 149/149 passed
- `cd frontend; npm run typecheck`: passed
- `cd frontend; npm run build`: passed
- `$env:JARVIS_E2E_PORT='5174'; npm run test:e2e`: 7 passed, 1 conditional skip
- Compileall, Ruff, required-services local integration, ledger, and
  `git diff --check`: passed

### Files Changed

- `src/adapters/file_run_state_repository.py`
- `tests/test_file_run_state_repository.py`
- `.gitignore`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_208.md`
- `docs/superpowers/specs/2026-08-18-bounded-run-state-directory-entries-design.md`
- `docs/superpowers/plans/2026-08-18-bounded-run-state-directory-entries.md`
- `docs/reports/AUDIT_REPORT_198.md` (removed from rolling window)

---

## Iteration #207 - 2026-08-18

**Protocol**: Bounded Plugin root discovery entries
**Status**: Complete

### Achievements

- Added an 8,192-entry budget to `PluginLoader` direct-root discovery using an
  incremental `os.scandir()` snapshot instead of unbounded `Path.iterdir()`
  materialization.
- Rejected the entire discovery snapshot at the first over-budget entry before
  reading any `manifest.json`, and cleared any prior discovery snapshot on
  overflow.
- Preserved exact-budget acceptance, deterministic name ordering, direct-child
  scope, and the existing per-Plugin validation/isolation behavior.
- Added exact-limit, overflow short-circuit, stale-snapshot, and scanner-stop
  assertions to the canonical Plugin SDK coverage.

### Verification

- `python tests/run_all.py`: 818 total (816 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1741 total (1739 passed, 2 skipped)
- `python -m unittest tests.test_plugin_sdk`: 125 passed
- `cd frontend; npm test -- --run`: 149/149 passed
- `cd frontend; npm run typecheck`: passed
- `cd frontend; npm run build`: passed
- `$env:JARVIS_E2E_PORT='5174'; npm run test:e2e`: 7 passed, 1 conditional skip
- Compileall, Ruff, required-services local integration, ledger, and
  `git diff --check`: passed

### Files Changed

- `src/core/kernel/plugin_sdk.py`
- `tests/test_plugin_sdk.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_207.md`
- `docs/superpowers/specs/2026-08-18-bounded-plugin-discovery-entries-design.md`
- `docs/superpowers/plans/2026-08-18-bounded-plugin-discovery-entries.md`
- `docs/reports/AUDIT_REPORT_197.md` (removed from rolling window)

---

## Iteration #206 - 2026-08-18

**Protocol**: Bounded API query ingress across all adapters
**Status**: Complete

### Achievements

- Added a 32 KiB raw-query pre-routing guard to the standard-library HTTP,
  FastAPI, and Express `/api/` boundaries so oversized input is rejected before
  route parsing, Core API proxying, or upstream dispatch.
- Preserved the stream route's decoded `model`/`messages` checks and unified all
  ingress failures as 413 `REQUEST_QUERY_TOO_LARGE` with the existing stable
  message.
- Replaced Express `app.listen` startup with a Node HTTP server using a bounded
  64 KiB header envelope, allowing valid 32 KiB queries to reach the
  application guard instead of failing as transport-level 431 responses.
- Declared 413 `ErrorResponse` results for every documented query-bearing
  OpenAPI operation and added exact-boundary, one-byte overflow,
  short-circuiting, transport, and contract regressions.

### Verification

- `python tests/run_all.py`: 815 total (813 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1738 total (1736 passed, 2 skipped)
- Focused Python/API contract tests: 321 passed
- `cd frontend; npm test -- --run`: 149/149 passed
- `cd frontend; npm test -- --run server.test.js`: 66/66 passed
- `cd frontend; npm run typecheck`: passed
- `cd frontend; npm run build`: passed
- `$env:JARVIS_E2E_PORT='5174'; npm run test:e2e`: 7 passed, 1 conditional skip
- Compileall, Ruff, required-services local integration, ledger, and
  `git diff --check`: passed

### Files Changed

- `src/main.py`
- `src/main_fastapi.py`
- `frontend/server.js`
- `contracts/core-api.openapi.json`
- `tests/test_main.py`
- `tests/test_main_fastapi_extended.py`
- `tests/test_api_contract.py`
- `frontend/server.test.js`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_206.md`
- `docs/superpowers/specs/2026-08-18-bounded-api-query-inputs-design.md`
- `docs/superpowers/plans/2026-08-18-bounded-api-query-inputs.md`
- `docs/reports/AUDIT_REPORT_196.md` (removed from rolling window)

---

## Iteration #205 - 2026-08-18

**Protocol**: Bounded Python GET Ollama stream query inputs
**Status**: Complete

### Achievements

- Rejected raw query text in the standard-library GET stream handler before
  `parse_qs`, then rejected decoded `model` and `messages` values over the
  shared 32 KiB UTF-8 budget before JSON parsing or upstream dispatch.
- Added FastAPI `Query(max_length=32768)` validation, stable 413 mapping for
  oversized stream query parameters, and explicit UTF-8 byte checks for
  multibyte values.
- Declared both GET query limits and the `REQUEST_QUERY_TOO_LARGE` 413 response
  in the shared OpenAPI contract while preserving valid SSE and fallback JSON
  behavior.
- Added raw, decoded, ASCII, multibyte, exact-limit, and contract regressions.

### Verification

- `python tests/run_all.py`: 812 total (810 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1731 total (1729 passed, 2 skipped)
- Focused Python/API contract tests: 314 passed
- `cd frontend; npm test -- --run`: 147/147 passed
- `cd frontend; npm run typecheck`: passed
- `cd frontend; npm run build`: passed
- `$env:JARVIS_E2E_PORT='5174'; npm run test:e2e`: 7 passed, 1 conditional skip
- Compileall, Ruff, required-services local integration, ledger, and
  `git diff --check`: passed

### Files Changed

- `src/main.py`
- `src/main_fastapi.py`
- `contracts/core-api.openapi.json`
- `tests/test_main.py`
- `tests/test_main_fastapi_extended.py`
- `tests/test_api_contract.py`
- `AGENTS.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_205.md`
- `docs/superpowers/specs/2026-08-18-bounded-stream-query-inputs-design.md`
- `docs/superpowers/plans/2026-08-18-bounded-stream-query-inputs.md`
- `docs/reports/AUDIT_REPORT_195.md` (removed from rolling window)

---

## Iteration #204 - 2026-08-18

**Protocol**: Bounded terminal child-process output
**Status**: Complete

### Achievements

- Replaced production `communicate()` collection in `TerminalExecutor` with
  concurrent binary stdout/stderr readers and independent 8 MiB raw-byte
  budgets.
- Reused the bounded collector in the parent `TerminalWorker` with its 64 KiB
  worker-response and 8 KiB diagnostic budgets; overflow kills the child
  before JSON decoding.
- Preserved visible output slices, timeout/non-zero result fields, worker
  protocol validation, and existing HTTP envelopes; explicit stream cleanup
  removes pipe resource warnings.
- Added stdout/stderr overflow regressions, worker wire overflow coverage, and
  registered the new tests in the aggregate suite.

### Verification

- `cd frontend; npm test -- --run`: 147/147 passed
- `cd frontend; npm test -- --run server.test.js`: 64/64 passed
- `cd frontend; npm run typecheck`: passed
- `cd frontend; npm run build`: passed
- `$env:JARVIS_E2E_PORT='5174'; npm run test:e2e`: 7 passed, 1 conditional skip
- `python tests/run_all.py`: 809 total (807 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1722 total (1720 passed, 2 skipped)
- Compileall, Ruff, required-services local integration, ledger, and `git diff --check`: passed

### Files Changed

- `src/core/kernel/terminal_executor.py`
- `src/core/kernel/terminal_worker.py`
- `tests/test_terminal_executor_extended_v2.py`
- `tests/test_terminal_worker.py`
- `tests/run_all.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_204.md`
- `docs/superpowers/specs/2026-08-18-bounded-terminal-process-output-design.md`
- `docs/superpowers/plans/2026-08-18-bounded-terminal-process-output.md`
- `docs/reports/AUDIT_REPORT_194.md` (removed from rolling window)

---

## Iteration #203 - 2026-08-18

**Protocol**: Bounded Express Git child-process output
**Status**: Complete

### Achievements

- Added an 8 MiB raw-byte budget independently to Git child-process stdout and
  stderr before decoding or route parsing.
- On the first byte beyond either budget, reject with an internal bounded
  output error, destroy both streams, and kill the child process; late child
  `error`/`close` events cannot settle the command a second time.
- Keep successful output decoding and existing non-zero exit diagnostics
  unchanged, while all three read-only Git routes retain their stable
  `GIT_COMMAND_FAILED` envelope.
- Added fake-child regressions for stdout overflow, stderr overflow, cleanup,
  and late-event settlement.

### Verification

- `cd frontend; npm test -- --run`: 147/147 passed
- `cd frontend; npm test -- --run server.test.js`: 64/64 passed
- `cd frontend; npm test -- --run server/core-api.test.js server.test.js`: 72/72 passed
- `cd frontend; npm run typecheck`: passed
- `cd frontend; npm run build`: passed
- `$env:JARVIS_E2E_PORT='5174'; npm run test:e2e`: 7 passed, 1 conditional skip
- `python tests/run_all.py`: 806 total (804 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1719 total (1717 passed, 2 skipped)
- Compileall, Ruff, required-services local integration, and `git diff --check`: passed

### Files Changed

- `frontend/server.js`
- `frontend/server.test.js`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_203.md`
- `docs/superpowers/specs/2026-08-18-bounded-express-git-output-design.md`
- `docs/superpowers/plans/2026-08-18-bounded-express-git-output.md`
- `docs/reports/AUDIT_REPORT_193.md` (removed from rolling window)

---

## Iteration #202 - 2026-08-18

**Protocol**: Bounded Core API responses and body deadlines
**Status**: Complete

### Achievements

- Replaced the Express Core API client's unbounded `Response.json()` path with
  an 8 MiB raw-byte stream reader that checks before retaining each chunk.
- Added early numeric `Content-Length` rejection, cumulative chunked-response
  enforcement, best-effort reader cancellation, and bounded UTF-8/JSON
  materialization while preserving `{ status, body }` forwarding.
- Kept the effective request deadline active through body consumption; a body
  stalled after headers now cancels and returns `CORE_API_UNAVAILABLE`, while
  oversized or malformed content retains `CORE_API_INVALID_RESPONSE`.
- Added RED/GREEN regressions for chunked overflow, declared-length overflow,
  non-settling cancellation, and a pending body after headers.

### Verification

- `cd frontend; npm test -- --run`: 145/145 passed
- `cd frontend; npm test -- --run server/core-api.test.js server.test.js`: 70/70 passed
- `cd frontend; npm run typecheck`: passed
- `cd frontend; npm run build`: passed
- `$env:JARVIS_E2E_PORT='5174'; npm run test:e2e`: 7 passed, 1 conditional skip
- `python tests/run_all.py`: 806 total (804 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1719 total (1717 passed, 2 skipped)
- Compileall, Ruff, required-services local integration, and `git diff --check`: passed

### Files Changed

- `frontend/server/core-api.js`
- `frontend/server/core-api.test.js`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_202.md`
- `docs/superpowers/specs/2026-08-18-bounded-core-api-responses-design.md`
- `docs/superpowers/plans/2026-08-18-bounded-core-api-responses.md`

---

## Iteration #201 - 2026-08-18

**Protocol**: Bounded Express Ollama proxy responses
**Status**: Complete

### Achievements

- Added an 8 MiB raw-byte budget to the Express Ollama proxy before JSON or
  NDJSON parsing for models, status, non-streaming chat, HTTP error bodies, and
  streaming chat responses.
- Destroyed oversized upstream responses at the first byte beyond the budget,
  separated transport failures from overflow handling, and preserved existing
  502 API envelopes and `OLLAMA_STREAM_ERROR` SSE framing.
- Added controlled chunked >8 MiB fixtures covering models, status, both chat
  modes, and early upstream close behavior; normal response and error paths
  remain covered.

### Verification

- `cd frontend; npm test -- --run`: 141/141 passed
- `cd frontend; npm test -- --run server.test.js`: 62/62 passed
- `cd frontend; npm run typecheck`: passed
- `cd frontend; npm run build`: passed
- `$env:JARVIS_E2E_PORT='5174'; npm run test:e2e`: 7 passed, 1 conditional skip
- `python tests/run_all.py`: 806 total (804 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1719 total (1717 passed, 2 skipped)
- Compileall, Ruff, required-services local integration, and `git diff --check`: passed

### Files Changed

- `frontend/server.js`
- `frontend/server.test.js`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_201.md`
- `docs/superpowers/specs/2026-08-18-bounded-express-ollama-proxy-design.md`
- `docs/superpowers/plans/2026-08-18-bounded-express-ollama-proxy.md`

---

## Iteration #200 - 2026-08-18

**Protocol**: Bounded Role Tool arguments and results
**Status**: Complete

### Achievements

- Added an exact capped canonical-JSON size counter for the Role Tool
  protocol, preserving its existing JSON type range and byte-for-byte output.
- Preflighted model call arguments and parent-owned handler results before
  full validation/normalization, preserving `argument_too_large`,
  `result_too_large`, malformed-value, and handler-exception contracts.
- Added canonical differential tests, exact-limit/overflow checks, a traced
  2 MiB result regression, and an `OverflowError` handler-exception regression.

### Verification

- `python tests/run_all.py`: 806 total (804 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1719 total (1717 passed, 2 skipped)
- Compileall, Ruff, local integration, and `git diff --check`: passed

### Files Changed

- `src/core/contracts/role_tool_protocol.py`
- `src/core/brain/role_tools.py`
- `tests/test_role_tool_protocol.py`
- `tests/test_role_tools.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_200.md`
- `docs/superpowers/specs/2026-08-18-bounded-role-tool-results-design.md`
- `docs/superpowers/plans/2026-08-18-bounded-role-tool-results.md`

---

## Iteration #199 - 2026-08-18

**Protocol**: Bounded Plugin Broker handler results
**Status**: Complete

### Achievements

- Added an exact canonical-JSON size counter that stops at the first byte
  beyond a caller-provided budget without materializing the complete value.
- Applied the counter to parent-owned Plugin Broker handler results so an
  oversized result is denied before temporary serialization copies are made;
  existing `result_too_large`, invalid-result, exchange, and event contracts
  remain unchanged.
- Added canonical-size differential tests, exact-limit/overflow checks, and a
  traced 2 MiB handler-result allocation regression.

### Verification

- `python tests/run_all.py`: 802 total (800 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1715 total (1713 passed, 2 skipped)
- Compileall, Ruff, local integration, and `git diff --check`: passed

### Files Changed

- `src/core/contracts/plugin_worker_protocol.py`
- `src/core/kernel/plugin_broker.py`
- `tests/test_plugin_worker_protocol.py`
- `tests/test_plugin_broker.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_199.md`
- `docs/superpowers/specs/2026-08-18-bounded-plugin-broker-results-design.md`
- `docs/superpowers/plans/2026-08-18-bounded-plugin-broker-results.md`

---

## Iteration #198 - 2026-08-18

**Protocol**: Bounded RoleWorker event frames
**Status**: Complete

### Achievements

- Added a 64 KiB Worker event-envelope allowance and made the parent request
  `max_output_bytes + allowance + 1` bytes from `Connection.recv_bytes()`.
- Discarded the sentinel-overflow frame before UTF-8, JSON, or WorkerEvent
  decoding while preserving existing transport-error and lifecycle handling.
- Added regressions for the exact receive bound and overflow non-forwarding;
  custom output budgets remain supported.

### Verification

- `python tests/run_all.py`: 799 total (797 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1712 total (1710 passed, 2 skipped)
- `python -m unittest tests.test_role_worker -q`: 32 passed
- Compileall, Ruff, and `git diff --check`: passed

### Files Changed

- `src/core/brain/role_worker.py`
- `tests/test_role_worker.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_198.md`
- `docs/superpowers/specs/2026-08-18-bounded-role-worker-events-design.md`
- `docs/superpowers/plans/2026-08-18-bounded-role-worker-events.md`

---

## Iteration #197 - 2026-08-18

**Protocol**: Bounded Ollama and local integration responses
**Status**: Complete

### Achievements

- Replaced unbounded Ollama `Response.json()` and `iter_lines()` consumption
  with bounded chunk and NDJSON line readers: 8 MiB total, 64 KiB per line,
  and 8 KiB transport chunks.
- Applied the same 8 MiB sentinel read to local integration JSON, HTTP error,
  and SSE responses, including a guard for already-materialized SSE strings.
- Preserved valid response shapes and existing error handling while rejecting
  oversized or malformed upstream bodies before downstream parsing.
- Added string `Content-Length`, body, line, cumulative-stream, and real local
  fixture integration regressions; included the new boundary suite in the
  aggregate runner.

### Verification

- `python tests/run_all.py`: 797 total (795 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1710 total (1708 passed, 2 skipped)
- `venv\\Scripts\\python.exe scripts\\ci_local_integration.py --require-services --timeout 30`: passed
- Compileall, Ruff, and `git diff --check`: passed

### Files Changed

- `src/core/kernel/ollama_manager.py`
- `scripts/local_integration_profile.py`
- `tests/test_ollama_manager.py`
- `tests/test_ollama_manager_extended.py`
- `tests/test_local_integration_profile.py`
- `tests/run_all.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_197.md`
- `docs/superpowers/specs/2026-08-18-bounded-ollama-responses-design.md`
- `docs/superpowers/plans/2026-08-18-bounded-ollama-responses.md`

---

## Iteration #196 - 2026-08-18

**Protocol**: Bounded Plugin Worker input lines
**Status**: Complete

### Achievements

- Changed the child-only Plugin Worker to read lifecycle and Broker protocol
  lines with a `MAX_PLUGIN_WORKER_LINE_BYTES + 1` sentinel bound before
  decoding.
- Preserved the existing protocol rejection and worker-exit behavior for
  oversized lines.
- Added a regression that records the exact bounded `readline` request and
  included the full Plugin Worker entrypoint suite in the canonical aggregate.

### Verification

- `python tests/run_all.py`: 791 total (789 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1704 total (1702 passed, 2 skipped)
- Compileall, Ruff, and `git diff --check`: passed

### Files Changed

- `src/runtime/plugin_worker.py`
- `tests/test_plugin_worker_entrypoint.py`
- `tests/run_all.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_196.md`
- `docs/superpowers/specs/2026-08-18-bounded-plugin-worker-input-design.md`
- `docs/superpowers/plans/2026-08-18-bounded-plugin-worker-input.md`

---

## Iteration #195 - 2026-08-18

**Protocol**: Bounded CLI JSON inputs and AgentFactory CLI exits
**Status**: Complete

### Achievements

- Added a shared 8 MiB, one-sentinel UTF-8 JSON reader for local CLI file
  inputs, rejecting oversized and stat-underreported files before decoding.
- Applied the bounded reader to `agent_factory.py batch`,
  `context_compressor.py compress`, and `role_registry.py register`.
- Restored successful `get`, `dispatch`, `dispatch_cap`, and `batch` paths in
  `agent_factory.py` by keeping exit codes inside their argument/error guards.
- Added direct-script `src` path bootstrap so all three documented CLIs work
  without a preconfigured `PYTHONPATH`.
- Added real subprocess regressions for exact-limit reads, post-stat growth,
  invalid UTF-8, valid batch input, and all three oversized CLI inputs.

### Verification

- `python tests/run_all.py`: 772 total (770 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1703 total (1701 passed, 2 skipped)
- Compileall, Ruff, and `git diff --check`: passed

### Files Changed

- `src/core/contracts/bounded_json.py`
- `src/core/brain/agent_factory.py`
- `src/core/brain/context_compressor.py`
- `src/core/brain/role_registry.py`
- `tests/test_bounded_cli_inputs.py`
- `tests/run_all.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_195.md`
- `docs/superpowers/specs/2026-08-18-bounded-cli-json-inputs-design.md`
- `docs/superpowers/plans/2026-08-18-bounded-cli-json-inputs.md`

---

## Iteration #194 - 2026-08-18

**Protocol**: Bounded Worker and writable MemoryStore input reads
**Status**: Complete

### Achievements

- Added a 32 KiB byte ceiling to the process-isolated Terminal Worker stdin
  request before JSON decoding, preserving the existing failure response shape.
- Added an 8 MiB descriptor-read ceiling for writable MemoryStore entry
  candidates, so oversized entries are skipped and oversized probes are not
  deleted.
- Added a 32 KiB UTF-8 byte ceiling to `WorkerTaskRequest.prompt` before a
  task can be serialized into a child process.
- Added regressions for each boundary and preserved existing wire fields,
  MemoryStore parsing, and worker lifecycle behavior.

### Verification

- `python tests/run_all.py`: 765 total (763 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1696 total (1694 passed, 2 skipped)
- Compileall, Ruff, and `git diff --check`: passed
- `venv\\Scripts\\python.exe scripts/ci_local_integration.py --require-services`: passed

### Files Changed

- `src/core/kernel/terminal_worker.py`
- `src/core/brain/context_compressor.py`
- `src/core/contracts/worker_protocol.py`
- `tests/test_terminal_worker.py`
- `tests/test_context_compressor.py`
- `tests/test_worker_protocol.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_194.md`
- `docs/superpowers/specs/2026-08-18-bounded-worker-and-memory-inputs-design.md`
- `docs/superpowers/plans/2026-08-18-bounded-worker-and-memory-inputs.md`

---

## Iteration #193 - 2026-08-18

**Protocol**: Bounded MemoryStore entry target writes
**Status**: Complete

### Achievements

- Added an `lstat()` preflight for deterministic MemoryStore entry targets;
  symlinks, reparse points, directories, and other non-regular objects are
  rejected before body construction or writing.
- Preserved replacement of existing regular entries and left both a rejected
  link and its external target unchanged.
- Added a regression proving the previous path-level write followed an entry
  symlink.

### Verification

- `python tests/run_all.py`: 762 total (760 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1693 total (1691 passed, 2 skipped)
- Compileall, Ruff, and `git diff --check`: passed

### Files Changed

- `src/core/brain/context_compressor.py`
- `tests/test_context_compressor.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_193.md`
- `docs/reports/AUDIT_REPORT_183.md` (removed from rolling window)
- `docs/superpowers/specs/2026-08-18-bounded-memory-store-entry-target-design.md`
- `docs/superpowers/plans/2026-08-18-bounded-memory-store-entry-target.md`

---

## Iteration #192 - 2026-08-18

**Protocol**: Bounded writable MemoryStore index reads
**Status**: Complete

### Achievements

- Added an 8 MiB bounded descriptor read for writable `MEMORY.md` index
  updates, reusing regular-file, reparse-point, identity, and post-open size
  checks.
- Validated the index before publishing an entry file and before deleting a
  probe candidate, preserving existing files when the index is oversized or
  unstable.
- Added exact-limit, stat-underreported growth, oversized-write, and probe
  preservation regressions while keeping cross-instance/process locking tests.

### Verification

- `python tests/run_all.py`: 761 total (759 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1692 total (1690 passed, 2 skipped)
- Compileall, Ruff, and `git diff --check`: passed

### Files Changed

- `src/core/brain/context_compressor.py`
- `tests/test_context_compressor.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_192.md`
- `docs/reports/AUDIT_REPORT_182.md` (removed from rolling window)
- `docs/superpowers/specs/2026-08-18-bounded-memory-store-index-design.md`
- `docs/superpowers/plans/2026-08-18-bounded-memory-store-index.md`

---

## Iteration #191 - 2026-08-18

**Protocol**: Bounded RoleWorker output normalization
**Status**: Complete

### Achievements

- Replaced the RoleWorker result normalizer's full `json.dumps()` allocation
  with `JSONEncoder.iterencode()` and cumulative UTF-8 byte accounting.
- Preserved sorted keys, compact separators, `ensure_ascii=False`, `default=str`,
  JSON round-trip normalization, and the existing output-limit error contract.
- Added a regression proving the first oversized encoder chunk stops processing
  and no unbounded `json.dumps()` call is made.

### Verification

- `python tests/run_all.py`: 756 total (754 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"` with the local Ollama fixture on port 11434: 1687 total (1685 passed, 2 skipped)
- `python -m unittest tests.test_role_worker -v`: 30/30 passed
- Compileall, Ruff, `git diff --check`, frontend Vitest/Playwright/typecheck/build,
  and required-services integration: passed

### Files Changed

- `src/core/brain/role_worker.py`
- `tests/test_role_worker.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_191.md`
- `docs/reports/AUDIT_REPORT_181.md` (removed from rolling window)
- `docs/superpowers/specs/2026-08-18-bounded-role-worker-output-design.md`
- `docs/superpowers/plans/2026-08-18-bounded-role-worker-output.md`

---

## Iteration #190 - 2026-08-18

**Protocol**: Bounded role-task persistence snapshots
**Status**: Complete

### Achievements

- Added an 8 MiB bounded binary reader for `RoleTaskRecordRepository` with a
  stat precheck, one sentinel byte, and fail-closed handling for oversized or
  stat-underreported snapshots.
- Added a matching bounded `JSONEncoder.iterencode()` writer. Oversized saves
  raise before replacing the previous atomic snapshot.
- Preserved the Worker protocol, retained-record limit, RLock, malformed-file
  empty-list behavior, and orphan reconciliation semantics.
- Added regressions for exact-budget reads, growth after stat, oversized
  recovery, and atomic oversized-save rejection.

### Verification

- `python tests/run_all.py`: 755 total (753 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"` with the local Ollama fixture on port 11434: 1686 total (1684 passed, 2 skipped)
- `python -m unittest tests.test_role_task_persistence -v`: 17/17 passed
- Compileall, Ruff, `git diff --check`, frontend Vitest/Playwright/typecheck/build,
  and required-services integration: passed

### Files Changed

- `src/adapters/role_task_record_repository.py`
- `tests/test_role_task_persistence.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_190.md`
- `docs/reports/AUDIT_REPORT_180.md` (removed from rolling window)
- `docs/superpowers/specs/2026-08-18-bounded-role-task-persistence-design.md`
- `docs/superpowers/plans/2026-08-18-bounded-role-task-persistence.md`

---

## Iteration #189 - 2026-08-18

**Protocol**: Bounded FileCapabilityStore published tree verification
**Status**: Complete

### Achievements

- Replaced `os.walk()` and its full per-directory name lists with an explicit
  `os.scandir()` stack that closes iterators promptly.
- Enforced `max_files` one published entry at a time and retained the existing
  `REVISION_DRIFT`, redirect, symlink, special-file, and unknown-file checks.
- Added a regression proving the verifier stops at the first over-limit entry.

### Verification

- `python tests/run_all.py`: 755 total (753 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1682 total (1680 passed, 2 skipped)
- FileCapabilityStore 49/49, Vitest 137/137, Playwright 7/1, typecheck, build,
  required-services integration, Ruff, compileall, and `git diff --check`: passed

### Files Changed

- `src/adapters/file_capability_store.py`
- `tests/test_file_capability_store.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_189.md`
- `docs/reports/AUDIT_REPORT_179.md` (removed from rolling window)
- `docs/superpowers/specs/2026-08-18-bounded-published-tree-verification-design.md`
- `docs/superpowers/plans/2026-08-18-bounded-published-tree-verification.md`

---

## Iteration #188 - 2026-08-18

**Protocol**: Bounded FileCapabilityStore archive entry metadata
**Status**: Complete

### Achievements

- Reused `ZipFile.filelist` with an early `max_files` check instead of copying
  the complete archive entry list through `infolist()`.
- Removed the second full-size logical-entry list; bounded logical path types
  preserve file/directory conflict checks after metadata size validation.
- Applied the same bounded entry source during revision publication and added a
  regression that rejects any future `infolist()` dependency.

### Verification

- `python tests/run_all.py`: 754 total (752 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1681 total (1679 passed, 2 skipped)
- FileCapabilityStore 48/48, Vitest 137/137, Playwright 7/1, typecheck, build,
  required-services integration, Ruff, compileall, and `git diff --check`: passed

### Files Changed

- `src/adapters/file_capability_store.py`
- `tests/test_file_capability_store.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_188.md`
- `docs/reports/AUDIT_REPORT_178.md` (removed from rolling window)
- `docs/superpowers/specs/2026-08-18-bounded-capability-archive-entries-design.md`
- `docs/superpowers/plans/2026-08-18-bounded-capability-archive-entries.md`

---

## Iteration #187 - 2026-08-18

**Protocol**: Bounded FileRunStateRepository recovery reads
**Status**: Complete

### Achievements

- Added one bounded binary recovery reader with an 8 MiB per-file budget and
  one sentinel byte, covering active manifests, revision files, archives,
  revision verification, and atomic read-back.
- Added a 32 MiB aggregate budget for the six authenticated recovery files;
  stat-underreported growth is rejected before decoding or digest comparison.
- Preserved HMAC, revision, archive, idempotent retry, and public StoredRunState
  contracts while updating the read-back regression to target the shared helper.

### Verification

- `python tests/run_all.py`: 753 total (751 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1680 total (1678 passed, 2 skipped)
- Capability/API impact suite: 469/469 passed; FileRunState persistence: 26 total (24 passed, 2 skipped)
- Ruff, compileall, Vitest 137, Playwright 7/1, typecheck, build, required-services integration, and `git diff --check`: passed

### Files Changed

- `src/adapters/file_run_state_repository.py`
- `tests/test_file_run_state_repository.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_187.md`
- `docs/reports/AUDIT_REPORT_177.md` (removed from rolling window)
- `docs/superpowers/specs/2026-08-18-bounded-run-state-reads-design.md`
- `docs/superpowers/plans/2026-08-18-bounded-run-state-reads.md`

---

## Iteration #186 - 2026-08-18

**Protocol**: Bounded Capability Registry tree traversal
**Status**: Complete

### Achievements

- Replaced recursive `Path.rglob("*")` hashing traversal with an iterative
  `os.scandir()` stack that closes each directory enumerator promptly.
- Added an 8,192-entry non-ignored tree budget, preventing directory-only or
  deeply nested trees from consuming unbounded traversal work while leaving
  ordinary capability trees unchanged.
- Preserved ignored paths, symlink rejection, deterministic file selection,
  and `tree_file_limit` precedence when file count exceeds `_MAX_FILES`.
- Added regressions for the new tree-entry boundary and the existing file-count
  boundary.

### Verification

- `python tests/run_all.py`: 752 total (750 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1679 total (1677 passed, 2 skipped)
- Capability/API impact suites: 469/469 passed
- Ruff, compileall, Vitest 137, Playwright 7/1, typecheck, build, required-services integration, and `git diff --check`: passed

### Files Changed

- `src/core/kernel/capability_registry.py`
- `tests/test_capability_registry.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_186.md`
- `docs/reports/AUDIT_REPORT_176.md` (removed from rolling window)
- `docs/superpowers/specs/2026-08-18-bounded-capability-tree-traversal-design.md`
- `docs/superpowers/plans/2026-08-18-bounded-capability-tree-traversal.md`

---

## Iteration #185 - 2026-08-18

**Protocol**: Bounded Capability Registry candidate collections
**Status**: Complete

### Achievements

- Replaced full `iterdir()` and `rglob()` candidate lists with a shared
  heap-based selection window bounded by `_MAX_CHILDREN` or `_MAX_FILES`.
- Continued counting every candidate so existing `*_child_limit` and
  `tree_file_limit` errors remain truthful, while deterministic smallest-name
  selection, ignored paths, symlink rejection, and stable digests remain intact.
- Added a bounded-collector regression that proves a 5,001-item stream retains
  only a constant-size live selection window.

### Verification

- `python tests/run_all.py`: 751 total (749 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1678 total (1676 passed, 2 skipped)
- Capability/API impact suites: 468/468 passed
- Ruff, compileall, Vitest 137, Playwright 7/1, typecheck, build, required-services integration, and `git diff --check`: passed

### Files Changed

- `src/core/kernel/capability_registry.py`
- `tests/test_capability_registry.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_185.md`
- `docs/reports/AUDIT_REPORT_175.md` (removed from rolling window)
- `docs/superpowers/specs/2026-08-18-bounded-capability-registry-collections-design.md`
- `docs/superpowers/plans/2026-08-18-bounded-capability-registry-collections.md`

---

## Iteration #184 - 2026-08-18

**Protocol**: Bounded Capability Registry content reads
**Status**: Complete

### Achievements

- Replaced unbounded Skill/Plugin metadata reads and tree-hash streaming with
  one binary read capped at 1 MiB plus a sentinel byte per file.
- Added a stat precheck for the fast rejection path while retaining the
  post-open sentinel check for files that grow after the precheck; tree digest
  size fields now use the actual bounded content length.
- Isolated Plugin JSON `RecursionError` and parser `ValueError` resource
  failures to the malformed candidate, preserving valid sibling discovery and
  existing error codes for oversized Skill and Plugin manifests.
- Strengthened regressions to reject chunked reads, pin a stable digest vector,
  exercise the real 5,000-digit JSON integer limit, and cover both manifest
  overflow paths.

### Verification

- `python tests/run_all.py`: 750 total (748 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1677 total (1675 passed, 2 skipped)
- Capability Registry and API impact suites: 467/467 passed
- Ruff, compileall, Vitest 137, Playwright 7/1, typecheck, build, required-services integration, and `git diff --check`: passed

### Files Changed

- `src/core/kernel/capability_registry.py`
- `tests/test_capability_registry.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_184.md`
- `docs/reports/AUDIT_REPORT_174.md` (removed from rolling window)
- `docs/superpowers/specs/2026-08-18-bounded-capability-registry-reads-design.md`
- `docs/superpowers/plans/2026-08-18-bounded-capability-registry-reads.md`

---

## Iteration #183 - 2026-08-18

**Protocol**: Bounded Plugin Manifest repository reads
**Status**: Complete

### Achievements

- Replaced unbounded Plugin Manifest text reads with a 64 KiB binary budget,
  a pre-open size check, and one sentinel byte for growth-race detection.
- Decodes and parses only bounded UTF-8 bytes before reusing the strict
  Iteration 182 field, ID, permission, and sandbox policy validation.
- Isolated JSON parser `RecursionError` to the malformed candidate so a deeply
  nested sibling cannot prevent later valid Plugins from being discovered.
- Preserved runtime support, entrypoint validation timing, lifecycle locks,
  Worker/Broker contracts, HTTP inputs, and same-user sandbox limitations.

### Verification

- `python tests/run_all.py`: 747 total (745 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1674 total (1672 passed, 2 skipped)
- Plugin SDK, installation, Worker runtime, and process containment suites: 214/214 passed
- Ruff, compileall, Vitest 137, Playwright 7/1, typecheck, build, required-services integration, and `git diff --check`: passed

### Files Changed

- `src/core/kernel/plugin_sdk.py`
- `tests/test_plugin_sdk.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_183.md`
- `docs/reports/AUDIT_REPORT_173.md` (removed from rolling window)
- `docs/superpowers/specs/2026-08-17-bounded-plugin-manifest-read-design.md`
- `docs/superpowers/plans/2026-08-17-bounded-plugin-manifest-read.md`

---

## Iteration #182 - 2026-08-17

**Protocol**: Strict Plugin Manifest discovery validation
**Status**: Complete

### Achievements

- Routed repository Plugin discovery through exact local Manifest and sandbox
  validation before publishing a candidate to lifecycle callers.
- Required explicit repository `plugin_id` values matching their direct
  directory and exact scalar, list, element, and boolean field types; malformed
  siblings are logged and skipped without aborting valid Plugins.
- Limited generated Plugin IDs to the exact empty-string compatibility input,
  so `None`, booleans, and numeric values remain visible to validation and are
  rejected instead of silently repaired.
- Preserved direct empty-string ID generation, legacy/unknown runtime discovery,
  unsupported-runtime load errors, and the existing Worker/Broker contracts.

### Verification

- `python tests/run_all.py`: 743 total (741 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1670 total (1668 passed, 2 skipped)
- Plugin SDK, installation, Worker runtime, and process containment suites: 176/176 passed
- Ruff, compileall, Vitest 137, Playwright 7/1, typecheck, build, required-services integration, and `git diff --check`: passed

### Files Changed

- `src/core/kernel/plugin_sdk.py`
- `tests/test_plugin_sdk.py`
- `tests/test_plugin_sdk_extended.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_182.md`
- `docs/reports/AUDIT_REPORT_172.md` (removed from rolling window)
- `docs/superpowers/specs/2026-08-17-plugin-manifest-discovery-validation-design.md`
- `docs/superpowers/plans/2026-08-17-plugin-manifest-discovery-validation.md`

---

## Iteration #181 - 2026-08-17

**Protocol**: Plugin lifecycle concurrency ownership
**Status**: Complete

### Achievements

- Added one reentrant lifecycle boundary to each service-owned `PluginManager`
  and its `PluginLoader`, serializing discovery, registry reads, load, enable,
  disable, unload, bulk load, and close.
- Concurrent exact loads of one Plugin now create one Worker generation and
  return the same `PluginInstance`; a partial start cannot be overwritten and
  lose its process owner.
- Preserved deterministic close order, identity validation, bounded Worker
  deadlines, unconfirmed-termination retention, and control-exception cleanup.
- Added a deterministic gated-start race regression to the already aggregated
  Plugin coordinator suite.

### Verification

- `python tests/run_all.py`: 741 total (739 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1668 total (1666 passed, 2 skipped)
- Plugin SDK, installation, Worker runtime, and process containment suites: 174/174 passed
- Ruff, compileall, Vitest 137, Playwright 7/1, typecheck, build, required-services integration, and `git diff --check`: passed

### Files Changed

- `src/core/kernel/plugin_sdk.py`
- `tests/test_plugin_sdk.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_181.md`
- `docs/reports/AUDIT_REPORT_171.md` (removed from rolling window)
- `docs/superpowers/specs/2026-08-17-plugin-lifecycle-concurrency-design.md`
- `docs/superpowers/plans/2026-08-17-plugin-lifecycle-concurrency.md`

---

## Iteration #180 - 2026-08-17

**Protocol**: Plugin Worker process-tree containment
**Status**: Complete

### Achievements

- Added a platform containment boundary to `SubprocessPluginRuntime`: POSIX
  workers start in a new process group, while Windows workers attach to a Job
  Object with kill-on-close semantics.
- Close now performs graceful and forceful tree termination, confirms the
  direct process and all descendants are gone, and only then releases the Job
  Object/process-group and worker temporary-directory ownership.
- Attachment failure is fail-closed and reaps the direct worker. Unconfirmed
  tree, reader, or containment cleanup retains ownership for a later `close()`
  retry instead of reporting termination success.
- Added real Windows descendant-process coverage plus launch, attachment,
  failure-reaping, and retry-boundary regressions to the aggregate suite.

### Verification

- `python tests/run_all.py`: 740 total (738 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1667 total (1665 passed, 2 skipped)
- Plugin Worker, Broker, SDK, protocol, installation, entrypoint, and process containment suites: passed
- Ruff, compileall, Vitest 137, Playwright 7/1, typecheck, build, required-services integration, and `git diff --check`: passed

### Files Changed

- `src/core/kernel/process_containment.py`
- `src/adapters/subprocess_plugin_runtime.py`
- `tests/test_process_containment.py`
- `tests/test_subprocess_plugin_runtime.py`
- `tests/run_all.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_180.md`
- `docs/reports/AUDIT_REPORT_170.md` (removed from rolling window)
- `docs/superpowers/specs/2026-08-17-plugin-worker-process-tree-design.md`
- `docs/superpowers/plans/2026-08-17-plugin-worker-process-tree.md`

---

## Iteration #179 - 2026-08-17

**Protocol**: RoleRegistry deep inheritance resolution
**Status**: Complete

### Achievements

- Replaced recursive `RoleRegistry._resolve_inheritance()` traversal with
  explicit parent-chain collection and reverse folding, so valid acyclic role
  graphs can be resolved beyond Python's recursion limit.
- Preserved parent-first capability, constraint, and tool de-duplication;
  child metadata precedence; maximum priority; missing-parent fallback; and
  detached result ownership.
- Added a 1100-role regression and registered it in the aggregate suite.

### Verification

- `python tests/run_all.py`: 736 total (734 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1659 total (1657 passed, 2 skipped)
- Role registry suites: 81/81 passed
- Ruff, compileall, Vitest 137, Playwright 7/1, typecheck, build, required-services integration, and `git diff --check`: passed

### Files Changed

- `src/core/brain/role_registry.py`
- `tests/test_role_registry_extended_v2.py`
- `tests/run_all.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_179.md`
- `docs/reports/AUDIT_REPORT_169.md` (removed from rolling window)
- `docs/superpowers/specs/2026-08-17-role-registry-deep-inheritance-design.md`
- `docs/superpowers/plans/2026-08-17-role-registry-deep-inheritance.md`

---

## Iteration #178 - 2026-08-17

**Protocol**: Role registry inheritance cycle rejection
**Status**: Complete

### Achievements

- Rejected direct and indirect `parent_role` cycles at the `RoleRegistry`
  registration boundary with a deterministic `ValueError` path.
- Performed validation and insertion under the same lock, so a rejected cycle
  cannot partially mutate the registry or race with another registration.
- Preserved duplicate-name precedence, missing-parent forward references,
  inheritance merge semantics, snapshot ownership, serialization, and public
  API behavior.

### Verification

- `python tests/run_all.py`: 735 total (733 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1658 total (1656 passed, 2 skipped)
- Role registry suites: 80/80 passed
- Ruff, compileall, Vitest 137, Playwright 7/1, typecheck, build, required-services integration, and `git diff --check`: passed

### Files Changed

- `src/core/brain/role_registry.py`
- `tests/test_role_registry_extended_v2.py`
- `tests/run_all.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_178.md`
- `docs/reports/AUDIT_REPORT_168.md` (removed from rolling window)
- `docs/superpowers/specs/2026-08-17-role-registry-inheritance-cycle-design.md`
- `docs/superpowers/plans/2026-08-17-role-registry-inheritance-cycle.md`

---

## Iteration #177 - 2026-08-17

**Protocol**: Role registry snapshot ownership
**Status**: Complete

### Achievements

- Detached caller-owned `AgentProfile` inputs during registration so later
  mutations cannot rewrite registry state.
- Returned detached `get()` and `list_roles()` profiles, including deep-copied
  nested metadata and inherited metadata merges.
- Preserved role inheritance, sorting, filtering, serialization, and service
  API behavior.

### Verification

- `python tests/run_all.py`: 733 total (731 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1656 total (1654 passed, 2 skipped)
- Role registry suites: 78/78 passed
- Warning-enabled ownership regressions: passed
- Ruff, compileall, Vitest 137, Playwright 7/1, typecheck, build, required-services integration, and `git diff --check`: passed

### Files Changed

- `src/core/brain/role_registry.py`
- `tests/test_role_registry_extended_v2.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_177.md`
- `docs/reports/AUDIT_REPORT_167.md` (removed from rolling window)
- `docs/superpowers/plans/2026-08-17-role-registry-snapshot-ownership.md`
- `docs/superpowers/specs/2026-08-17-role-registry-snapshot-ownership-design.md`

---

## Iteration #176 - 2026-08-17

**Protocol**: Role registry CLI success-path restoration
**Status**: Complete

### Achievements

- Restored the documented `get <role_name>` CLI path so a known role is
  resolved, printed as JSON, and returned with exit code 0.
- Restored `register <json_file>` so a valid profile is loaded and registered
  in the process-local registry before the command reports success.
- Kept missing arguments, unknown commands, unknown roles, inheritance,
  serialization, and service registry behavior unchanged.

### Verification

- `python tests/run_all.py`: 732 total (730 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1655 total (1653 passed, 2 skipped)
- Role registry suites: 77/77 passed
- Warning-enabled CLI regressions: passed
- Ruff, compileall, Vitest 137, Playwright 7/1, typecheck, build, required-services integration, and `git diff --check`: passed

### Files Changed

- `src/core/brain/role_registry.py`
- `tests/test_role_registry_extended_v2.py`
- `tests/run_all.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_176.md`
- `docs/reports/AUDIT_REPORT_166.md` (removed from rolling window)
- `docs/superpowers/plans/2026-08-17-role-registry-cli-exit.md`
- `docs/superpowers/specs/2026-08-17-role-registry-cli-exit-design.md`

---

## Iteration #175 - 2026-08-17

**Protocol**: TerminalExecutor shell parse failure normalization
**Status**: Complete

### Achievements

- Converted malformed or non-string direct `execute_shell()` tokenization
  errors into the existing zero-duration failed `TerminalResult` shape.
- Ensured unmatched shell input does not start a child process or create a
  successful audit record, while preserving parser error text for diagnosis.
- Kept empty/valid shell behavior, timeouts, policy checks, worker protocol,
  and HTTP contracts unchanged.

### Verification

- `python tests/run_all.py`: 730 total (728 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1653 total (1651 passed, 2 skipped)
- Terminal executor extended suite: 24/24 passed
- Warning-enabled affected regressions: passed
- Ruff, compileall, Vitest 137, Playwright 7/1, typecheck, build, required-services integration, and `git diff --check`: passed

### Files Changed

- `src/core/kernel/terminal_executor.py`
- `tests/test_terminal_executor_extended_v2.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_175.md`
- `docs/reports/AUDIT_REPORT_165.md` (removed from rolling window)
- `docs/superpowers/plans/2026-08-17-terminal-executor-shell-parse.md`
- `docs/superpowers/specs/2026-08-17-terminal-executor-shell-parse-design.md`

---

## Iteration #174 - 2026-08-17

**Protocol**: MemoryStore descriptor read failure isolation
**Status**: Complete

### Achievements

- Isolated post-open `fstat` and `read` `OSError` failures to the current
  MemoryStore candidate instead of aborting the bounded read-only scan.
- Preserved unconditional descriptor close and returned actual consumed bytes
  so the total scan budget remains truthful after a partial read.
- Kept writable identity checks, parse behavior, scan limits, file formats,
  locking, and public APIs unchanged.

### Verification

- `python tests/run_all.py`: 729 total (727 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1652 total (1650 passed, 2 skipped)
- MemoryStore tests: 26/26 passed
- Warning-enabled affected regressions: passed
- Ruff, compileall, Vitest 137, Playwright 7/1, typecheck, build, required-services integration, and `git diff --check`: passed

### Files Changed

- `src/core/brain/context_compressor.py`
- `tests/test_context_compressor.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_174.md`
- `docs/reports/AUDIT_REPORT_164.md` (removed from rolling window)
- `docs/superpowers/plans/2026-08-17-memory-store-descriptor-read-failure.md`
- `docs/superpowers/specs/2026-08-17-memory-store-descriptor-read-failure-design.md`

---

## Iteration #173 - 2026-08-17

**Protocol**: MemoryStore writable regular-file candidate boundary
**Status**: Complete

### Achievements

- Routed writable legacy loading and probe candidate parsing through regular,
  non-reparse descriptor reads with observed-file identity checks.
- Prevented symlink entries from exposing external Markdown through memory
  listing or being accepted and unlinked by probe cleanup.
- Preserved the old writable universal-newline behavior while leaving read-only
  byte budgets, file formats, locks, and public API shapes unchanged.

### Verification

- `python tests/run_all.py`: 728 total (726 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1651 total (1649 passed, 2 skipped)
- MemoryStore tests: 25/25 passed
- Warning-enabled affected regressions: passed
- Ruff, compileall, Vitest 137, Playwright 7/1, typecheck, build, required-services integration, and `git diff --check`: passed

### Files Changed

- `src/core/brain/context_compressor.py`
- `tests/test_context_compressor.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_173.md`
- `docs/reports/AUDIT_REPORT_163.md` (removed from rolling window)
- `docs/superpowers/plans/2026-08-17-memory-store-writable-regular-file.md`
- `docs/superpowers/specs/2026-08-17-memory-store-writable-regular-file-design.md`

---

## Iteration #172 - 2026-08-17

**Protocol**: MemoryStore Unicode frontmatter line separator preservation
**Status**: Complete

### Achievements

- Escaped NEL (`U+0085`) and Unicode line/paragraph separators (`U+2028`,
  `U+2029`) after unsafe JSON scalar encoding so `splitlines()` cannot split a
  quoted frontmatter field.
- Preserved exact Unicode title round-trips while retaining `ensure_ascii=False`
  for ordinary non-ASCII text and the existing legacy parser contract.
- Kept body semantics, frontmatter delimiters, index encoding, locking, and
  public APIs unchanged.

### Verification

- `python tests/run_all.py`: 726 total (724 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1649 total (1647 passed, 2 skipped)
- MemoryStore tests: 23/23 passed
- Warning-enabled affected regressions: passed
- Ruff, compileall, Vitest 137, Playwright 7/1, typecheck, build, required-services integration, and `git diff --check`: passed

### Files Changed

- `src/core/brain/context_compressor.py`
- `tests/test_context_compressor.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_172.md`
- `docs/reports/AUDIT_REPORT_162.md` (removed from rolling window)
- `docs/superpowers/plans/2026-08-17-memory-store-unicode-line-separator.md`
- `docs/superpowers/specs/2026-08-17-memory-store-unicode-line-separator-design.md`

---

## Iteration #171 - 2026-08-17

**Protocol**: MemoryStore probe deletion fail-closed parsing
**Status**: Complete

### Achievements

- Made `MemoryStore.delete_probe()` reject unreadable, undecodable, or
  malformed frontmatter candidates with `False` before any mutation.
- Preserved the candidate file and index on known read/parse failures while
  retaining exact type, ID, title-prefix, and constant-time token checks.
- Kept actual unlink and index-update failures visible; file formats, locks,
  loader behavior, and public API shapes are unchanged.

### Verification

- `python tests/run_all.py`: 725 total (723 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1648 total (1646 passed, 2 skipped)
- MemoryStore tests: 22/22 passed
- Warning-enabled affected regressions: passed
- Ruff, compileall, Vitest 137, Playwright 7/1, typecheck, build, required-services integration, and `git diff --check`: passed

### Files Changed

- `src/core/brain/context_compressor.py`
- `tests/test_context_compressor.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_171.md`
- `docs/reports/AUDIT_REPORT_161.md` (removed from rolling window)
- `docs/superpowers/plans/2026-08-17-memory-store-probe-delete-fail-closed.md`
- `docs/superpowers/specs/2026-08-17-memory-store-probe-delete-fail-closed-design.md`

---

## Iteration #170 - 2026-08-17

**Protocol**: MemoryStore frontmatter string encoding
**Status**: Complete

### Achievements

- JSON-encoded only newly written frontmatter values that cannot be represented
  safely on one legacy line, preserving ordinary unquoted file formatting.
- Parsed complete `---` delimiter lines instead of arbitrary substrings, so
  titles and bodies containing delimiters and newlines remain readable.
- Kept legacy unquoted frontmatter readable and reused decoded metadata for
  probe deletion; body metadata footer semantics and public APIs are unchanged.

### Verification

- `python tests/run_all.py`: 724 total (722 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1647 total (1645 passed, 2 skipped)
- MemoryStore tests: 21/21 passed
- Warning-enabled affected regressions: passed
- Ruff, compileall, Vitest 137, Playwright 7/1, typecheck, build, required-services integration, and `git diff --check`: passed

### Files Changed

- `src/core/brain/context_compressor.py`
- `tests/test_context_compressor.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_170.md`
- `docs/reports/AUDIT_REPORT_160.md` (removed from rolling window)
- `docs/superpowers/plans/2026-08-17-memory-store-frontmatter-encoding.md`
- `docs/superpowers/specs/2026-08-17-memory-store-frontmatter-encoding-design.md`

---

## Iteration #169 - 2026-08-17

**Protocol**: MemoryStore writable load fail-closed parsing
**Status**: Complete

### Achievements

- Writable `MemoryStore.load()` now skips an unreadable or malformed legacy
  entry instead of aborting the complete load transaction.
- The exception boundary is limited to file and known metadata parsing errors;
  valid sibling entries and memory-type filtering retain their existing order
  and behavior.
- Read-only bounded scanning, directory locking, entry formats, and public
  APIs remain unchanged.

### Verification

- `python tests/run_all.py`: 723 total (721 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1646 total (1644 passed, 2 skipped)
- MemoryStore tests: 20/20 passed
- Warning-enabled affected regressions: passed
- Ruff, compileall, Vitest 137, Playwright 7/1, typecheck, build, required-services integration, and `git diff --check`: passed

### Files Changed

- `src/core/brain/context_compressor.py`
- `tests/test_context_compressor.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_169.md`
- `docs/reports/AUDIT_REPORT_159.md` (removed from rolling window)
- `docs/superpowers/plans/2026-08-17-memory-store-load-fail-closed.md`
- `docs/superpowers/specs/2026-08-17-memory-store-load-fail-closed-design.md`

---

## Iteration #168 - 2026-08-17

**Protocol**: MemoryStore index inline encoding
**Status**: Complete

### Achievements

- Encoded control characters and line separators into visible ASCII escapes
  before writing MemoryStore index labels or summaries.
- Escaped backslashes and square brackets in Markdown link labels while
  retaining ordinary ASCII and Unicode text.
- Reused the encoded title for exact row matching, so repeated unsafe titles
  replace one row instead of appending or forging additional rows.
- Preserved original MemoryEntry values, entry IDs/files, summary raw-length
  bound, directory locking, and HTTP response shapes.

### Verification

- `python tests/run_all.py`: 722 total (720 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1645 total (1643 passed, 2 skipped)
- Context-compressor tests: 142/142 passed
- HTTP/Memory/read-only tests: 552/552 passed with ResourceWarning enabled
- Ruff, compileall, Vitest 137, Playwright 7/1, typecheck, build, and required-services integration: passed

### Files Changed

- `src/core/brain/context_compressor.py`
- `tests/test_context_compressor.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_168.md`
- `docs/reports/AUDIT_REPORT_158.md` (removed from rolling window)
- `docs/superpowers/plans/2026-08-17-memory-store-index-encoding.md`
- `docs/superpowers/specs/2026-08-17-memory-store-index-encoding-design.md`

---

## Iteration #167 - 2026-08-17

**Protocol**: Exact MemoryStore index title matching
**Status**: Complete

### Achievements

- Replaced whole-index and per-row substring checks with an exact Markdown
  link-label prefix match.
- Prevented a new title such as `foo` from replacing the existing `foobar`
  index row while retaining both distinct entry files and rows.
- Preserved exact-title replacement, duplicate-row behavior, directory
  transaction ownership, and all public/file formats.
- Registered the regression in the canonical aggregate MemoryStore class.

### Verification

- `python tests/run_all.py`: 721 total (719 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1644 total (1642 passed, 2 skipped)
- Context-compressor tests: 141/141 passed
- HTTP/Memory/read-only tests: 551/551 passed with ResourceWarning enabled
- Ruff, compileall, Vitest 137, Playwright 7/1, typecheck, build, and required-services integration: passed

### Files Changed

- `src/core/brain/context_compressor.py`
- `tests/test_context_compressor.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_167.md`
- `docs/reports/AUDIT_REPORT_157.md` (removed from rolling window)
- `docs/superpowers/plans/2026-08-17-memory-store-exact-index-title.md`
- `docs/superpowers/specs/2026-08-17-memory-store-exact-index-title-design.md`

---

## Iteration #166 - 2026-08-17

**Protocol**: MemoryStore directory transaction ownership
**Status**: Complete

### Achievements

- Replaced per-instance-only writable ownership with a canonical-directory
  process lock shared by all local MemoryStore instances.
- Added a Windows named mutex and POSIX regular-file `flock` so cooperating
  service processes cannot read and overwrite the same stale `MEMORY.md`.
- Kept store, probe deletion, writable load, and consolidate under one outer
  transaction while nested work uses explicit unlocked helpers.
- Preserved public APIs, entry/index Markdown formats, and the lock-free
  bounded read-only role-tool scanner.

### Verification

- `python tests/run_all.py`: 720 total (718 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1643 total (1641 passed, 2 skipped)
- Context-compressor tests: 140/140 passed
- HTTP/Memory/read-only tests: 550/550 passed with ResourceWarning enabled
- Ruff, compileall, Vitest 137, Playwright 7/1, typecheck, build, and required-services integration: passed

### Files Changed

- `src/core/brain/context_compressor.py`
- `tests/test_context_compressor.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_166.md`
- `docs/reports/AUDIT_REPORT_156.md` (removed from rolling window)
- `docs/superpowers/plans/2026-08-17-memory-store-directory-transaction.md`
- `docs/superpowers/specs/2026-08-17-memory-store-directory-lock-design.md`

---

## Iteration #165 - 2026-08-17

**Protocol**: MemoryStore mutation ownership
**Status**: Complete

### Achievements

- Added a per-instance reentrant mutation lock for writable MemoryStore
  transactions.
- Serialized entry writes, index updates, probe deletion, writable legacy
  loads, and consolidate's load/compress/store sequence.
- Prevented same-title concurrent writes from creating duplicate `MEMORY.md`
  rows while retaining both distinct entry files.
- Preserved read-only bounded scanning, file formats, and memory HTTP shapes.

### Verification

- `python tests/run_all.py`: 718 total (716 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1641 total (1639 passed, 2 skipped)
- Context-compressor tests: 138/138 passed
- HTTP/Memory/read-only tests: 361/361 passed with ResourceWarning enabled
- Ruff, compileall, Vitest 137, Playwright 7/1, typecheck, build, and required-services integration: passed

### Files Changed

- `src/core/brain/context_compressor.py`
- `tests/test_context_compressor.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_165.md`
- `docs/reports/AUDIT_REPORT_155.md` (removed from rolling window)
- `docs/superpowers/plans/2026-08-17-memory-store-mutation-ownership.md`
- `docs/superpowers/specs/2026-08-17-memory-store-mutation-ownership-design.md`

---

## Iteration #164 - 2026-08-17

**Protocol**: Truthful EventBus unsubscribe contract
**Status**: Complete

### Achievements

- Made `EventBus.unsubscribe()` return `True` only when an existing
  subscription record is actually removed.
- Rejected boolean, float, and other non-plain-integer IDs without mutating
  subscriptions, closing Python equality coercion with integer IDs.
- Preserved locked removal, missing-ID no-error behavior, subscriber ordering,
  and all callback semantics.
- Updated both unittest and pytest coverage to enforce the documented return
  contract.

### Verification

- `python tests/run_all.py`: 717 total (715 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1640 total (1638 passed, 2 skipped)
- EventBus unittest 42/42 and pytest 28/28 passed
- Affected Plugin/Broker/HTTP tests: 563/563 passed with ResourceWarning enabled
- Ruff, compileall, Vitest 137, Playwright 7/1, typecheck, build, and required-services integration: passed

### Files Changed

- `src/core/kernel/event_bus.py`
- `tests/test_event_bus.py`
- `tests/test_event_bus_extended.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_164.md`
- `docs/reports/AUDIT_REPORT_154.md` (removed from rolling window)
- `docs/superpowers/plans/2026-08-17-event-bus-unsubscribe-contract.md`
- `docs/superpowers/specs/2026-08-17-event-bus-unsubscribe-contract-design.md`

---

## Iteration #163 - 2026-08-17

**Protocol**: Atomic EventBus once-subscription claims
**Status**: Complete

### Achievements

- Made EventBus claim matching `once=True` subscriptions under its existing
  lock before invoking callbacks, guaranteeing at-most-once execution for
  concurrent and reentrant emits.
- Kept all user callbacks and exception isolation outside the lock.
- Avoided selecting wildcard subscribers twice when the emitted event type is
  itself `"*"`.
- Expanded the already-registered EventBus boundary class with concurrent,
  reentrant, and wildcard selection regressions.

### Verification

- `python tests/run_all.py`: 716 total (714 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1639 total (1637 passed, 2 skipped)
- EventBus unittest 41/41 and pytest 28/28 passed
- Affected Plugin/Broker/HTTP tests: 563/563 passed with ResourceWarning enabled
- Ruff, compileall, Vitest 137, Playwright 7/1, typecheck, build, and required-services integration: passed

### Files Changed

- `src/core/kernel/event_bus.py`
- `tests/test_event_bus_extended.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_163.md`
- `docs/reports/AUDIT_REPORT_153.md` (removed from rolling window)
- `docs/superpowers/plans/2026-08-17-event-bus-once-claim.md`
- `docs/superpowers/specs/2026-08-17-event-bus-once-claim-design.md`

---

## Iteration #162 - 2026-08-17

**Protocol**: EventBus subscription and history state boundaries
**Status**: Complete

### Achievements

- Moved EventBus subscription ID reservation into the same lock section as
  subscriber registration so concurrent callers receive unique IDs.
- Made `get_history()` accept only exact non-negative integer limits and return
  an empty list for zero instead of the complete history.
- Preserved callback execution outside the lock, chronological filtered reads,
  the fixed history capacity, and existing Event object identity.
- Registered the two deterministic EventBus state-boundary regressions exactly
  once in the canonical aggregate suite.

### Verification

- `python tests/run_all.py`: 713 total (711 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1636 total (1634 passed, 2 skipped)
- EventBus unittest 38/38 and pytest 28/28 passed
- Affected Plugin/Broker/HTTP tests: 563/563 passed with ResourceWarning enabled
- Ruff, compileall, Vitest 137, Playwright 7/1, typecheck, build, and required-services integration: passed

### Files Changed

- `src/core/kernel/event_bus.py`
- `tests/run_all.py`
- `tests/test_event_bus_extended.py`
- `tests/test_run_all_coverage.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_162.md`
- `docs/reports/AUDIT_REPORT_152.md` (removed from rolling window)
- `docs/superpowers/plans/2026-08-17-event-bus-state-boundaries.md`
- `docs/superpowers/specs/2026-08-17-event-bus-state-boundaries-design.md`

---

## Iteration #161 - 2026-08-17

**Protocol**: Bounded LLM compression history
**Status**: Complete

### Achievements

- Replaced the unbounded `LLMCompressor` history list with a lock-protected
  deque retaining the newest 1000 compression records.
- Made history reads return separate scalar dictionaries so consumers cannot
  rewrite retained action evidence.
- Serialized append, snapshot, and clear operations without holding the lock
  during Ollama calls or compression work.
- Registered the six focused LLM compression history regressions exactly once
  in the canonical aggregate suite.

### Verification

- `python tests/run_all.py`: 711 total (709 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1633 total (1631 passed, 2 skipped)
- All context-compressor tests: 137/137 passed
- Ruff, compileall, Vitest 137, Playwright 7/1, typecheck, build, and required-services integration: passed

### Files Changed

- `src/core/brain/context_compressor.py`
- `tests/run_all.py`
- `tests/test_context_compressor_llm.py`
- `tests/test_run_all_coverage.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_161.md`
- `docs/reports/AUDIT_REPORT_151.md` (removed from rolling window)
- `docs/superpowers/plans/2026-08-17-bounded-llm-compression-history.md`
- `docs/superpowers/specs/2026-08-17-bounded-llm-compression-history-design.md`

---

## Iteration #160 - 2026-08-17

**Protocol**: Atomic Ollama token telemetry ownership
**Status**: Complete

### Achievements

- Protected shared Ollama token totals, latest usage, and samples with one
  lock so concurrent chat and Role Worker updates cannot lose counts.
- Replaced copy-on-append sample storage with a fixed-capacity deque retaining
  the newest 60 entries.
- Made both token getters return independent value snapshots so callers cannot
  rewrite service-owned session totals or HTTP telemetry evidence.
- Registered all nine existing and new token-usage regressions exactly once in
  the canonical aggregate suite.

### Verification

- `python tests/run_all.py`: 705 total (703 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1630 total (1628 passed, 2 skipped)
- Focused Ollama and Role Worker tests: 106/106 passed with ResourceWarning enabled
- Ruff, compileall, Vitest 137, Playwright 7/1, typecheck, build, and required-services integration: passed

### Files Changed

- `src/core/kernel/ollama_manager.py`
- `tests/run_all.py`
- `tests/test_ollama_manager.py`
- `tests/test_run_all_coverage.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_160.md`
- `docs/reports/AUDIT_REPORT_150.md` (removed from rolling window)
- `docs/superpowers/plans/2026-08-17-token-usage-state-ownership.md`
- `docs/superpowers/specs/2026-08-17-token-usage-state-ownership-design.md`

---

## Iteration #159 - 2026-08-17

**Protocol**: Bounded orchestrator result history
**Status**: Complete

### Achievements

- Replaced the service-lifetime generic orchestrator history list with a deque
  retaining the newest 1000 task results.
- Added deep-copy ownership at both record and query boundaries so dispatch
  callers and history consumers cannot rewrite retained nested result data.
- Made `collect()` accept only exact non-negative integer limits, return an
  empty result for zero, and filter retained history before applying the
  newest-first result window.
- Preserved separate original-attempt and retry-summary evidence instead of
  relying on result-object aliasing to rewrite both history entries.

### Verification

- `python tests/run_all.py`: 696 total (694 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1626 total (1624 passed, 2 skipped)
- Focused orchestrator tests: 145/145 passed with ResourceWarning enabled
- Ruff, compileall, Vitest 137, Playwright 7/1, typecheck, build, and required-services integration: passed

### Files Changed

- `src/core/brain/orchestrator.py`
- `tests/run_all.py`
- `tests/test_orchestrator_extended_v2.py`
- `tests/test_run_all_coverage.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_159.md`
- `docs/reports/AUDIT_REPORT_149.md` (removed from rolling window)
- `docs/superpowers/plans/2026-08-17-bounded-orchestrator-history.md`
- `docs/superpowers/specs/2026-08-17-bounded-orchestrator-history-design.md`

---

## Iteration #158 - 2026-08-17

**Protocol**: Plugin API audit ownership and retention
**Status**: Complete

### Achievements

- Replaced the child-side Plugin API's unbounded access list with a
  lock-protected deque retaining the newest 1000 scalar records.
- Separated local, getter, and Worker sink dictionary ownership so plugin code
  cannot rewrite audit evidence later returned to the parent.
- Kept the sink outside the internal lock, added exact non-negative read-limit
  validation, and registered the existing Plugin API suite in the canonical
  aggregate runner.

### Verification

- `python tests/run_all.py`: 692 total (690 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1621 total (1619 passed, 2 skipped)
- Focused Plugin tests: 246/246 passed with ResourceWarning enabled
- Ruff, compileall, Vitest 137, Playwright 7/1, typecheck, build, and required-services integration: passed

### Files Changed

- `src/core/kernel/plugin_api.py`
- `tests/run_all.py`
- `tests/test_plugin_sdk.py`
- `tests/test_run_all_coverage.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_158.md`
- `docs/reports/AUDIT_REPORT_148.md` (removed from rolling window)
- `docs/superpowers/plans/2026-08-17-plugin-api-audit-ownership.md`
- `docs/superpowers/specs/2026-08-17-plugin-api-audit-ownership-design.md`

---

## Iteration #157 - 2026-08-17

**Protocol**: Bounded terminal audit history
**Status**: Complete

### Achievements

- Replaced the unbounded TerminalWorker and TerminalExecutor audit lists with
  lock-protected deques retaining the newest 1000 scalar records.
- Audit getters now validate an exact non-negative integer limit, return an
  empty snapshot for zero, and copy dictionaries so callers cannot rewrite
  stored evidence.
- Replaced the one-entry pseudo-boundary test with deterministic 1005-entry
  eviction regressions and added the existing executor audit class to the
  canonical aggregate suite with a registration guard.

### Verification

- `python tests/run_all.py`: 674 total (672 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1616 total (1614 passed, 2 skipped)
- Focused terminal tests: 66/66 passed with ResourceWarning enabled
- Ruff, compileall, Vitest 137, Playwright 7/1, typecheck, build, and required-services integration: passed

### Files Changed

- `src/core/kernel/terminal_executor.py`
- `src/core/kernel/terminal_worker.py`
- `tests/run_all.py`
- `tests/test_run_all_coverage.py`
- `tests/test_terminal_executor_extended_v2.py`
- `tests/test_terminal_worker.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_157.md`
- `docs/reports/AUDIT_REPORT_147.md` (removed from rolling window)
- `docs/superpowers/plans/2026-08-17-bounded-terminal-audit-history.md`
- `docs/superpowers/specs/2026-08-17-bounded-terminal-audit-history-design.md`

---

## Iteration #156 - 2026-08-17

**Protocol**: TerminalWorker concurrent lifecycle ownership
**Status**: Complete

### Achievements

- Added condition-protected child reservations to the default HTTP
  `TerminalWorker`, preventing sandbox cleanup while process communication is
  in flight.
- Close now fails new work closed, waits for active children, and lets exactly
  one immediate or waiting concurrent caller perform cleanup.
- Preserved cleanup-failure retry and added deterministic RED/GREEN tests for
  all three races without changing the fixed operation or wire contracts.

### Verification

- `python tests/run_all.py`: 666 total (664 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1610 total (1608 passed, 2 skipped)
- Focused terminal tests: 61/61 passed with ResourceWarning enabled
- Ruff, compileall, Vitest 137, Playwright 7/1, typecheck, build, and required-services integration: passed

### Files Changed

- `src/core/kernel/terminal_worker.py`
- `tests/test_terminal_worker.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_156.md`
- `docs/reports/AUDIT_REPORT_146.md` (removed from rolling window)
- `docs/superpowers/plans/2026-08-17-terminal-worker-lifecycle.md`
- `docs/superpowers/specs/2026-08-17-terminal-worker-lifecycle-design.md`

---

## Iteration #155 - 2026-08-17

**Protocol**: TerminalExecutor concurrent lifecycle ownership
**Status**: Complete

### Achievements

- Added condition-protected execution reservations so a sandboxed command owns
  its working directory until it returns.
- `close()` now rejects new sandbox work, waits for active reservations, and
  transfers cleanup ownership to exactly one concurrent closer.
- A transient cleanup failure retains the directory handle so a later close
  can retry instead of losing ownership.
- Added deterministic RED/GREEN coverage for both in-flight cleanup and two
  concurrent close waiters, then placed the lifecycle suite in the canonical
  aggregate runner.

### Verification

- `python tests/run_all.py`: 662 total (660 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1606 total (1604 passed, 2 skipped)
- Focused terminal tests: 57/57 passed
- Ruff, compileall, Vitest 137, Playwright 7/1, typecheck, build, and required-services integration: passed

### Files Changed

- `src/core/kernel/terminal_executor.py`
- `tests/run_all.py`
- `tests/test_run_all_coverage.py`
- `tests/test_terminal_executor_extended_v2.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_155.md`
- `docs/reports/AUDIT_REPORT_145.md` (removed from rolling window)
- `docs/superpowers/plans/2026-08-17-terminal-executor-lifecycle.md`
- `docs/superpowers/specs/2026-08-17-terminal-executor-lifecycle-design.md`

---

## Iteration #154 - 2026-08-17

**Protocol**: TerminalExecutor policy parameter enforcement
**Status**: Complete

### Achievements

- Enforced the existing `denied_commands` option before the allowlist and
  process-spawn path, so an explicit deny always wins and returns a
  fail-closed dangerous result.
- Made an omitted `execute_shell()` timeout inherit the executor's configured
  `default_timeout`, while preserving explicit per-call values.
- Added RED/GREEN regressions for both previously inert parameters and placed
  their test classes in the canonical aggregate suite with a configuration
  guard.

### Verification

- `python tests/run_all.py`: 659 total (657 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1603 total (1601 passed, 2 skipped)
- Focused terminal tests: 54/54 passed
- Ruff, compileall, Vitest 137, Playwright 7/1, typecheck, build, and required-services integration: passed

### Files Changed

- `src/core/kernel/terminal_executor.py`
- `tests/run_all.py`
- `tests/test_run_all_coverage.py`
- `tests/test_terminal_executor_extended_v2.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_154.md`
- `docs/reports/AUDIT_REPORT_144.md` (removed from rolling window)
- `docs/superpowers/plans/2026-08-17-terminal-executor-policy-parameters.md`
- `docs/superpowers/specs/2026-08-17-terminal-executor-policy-parameters-design.md`

---

## Iteration #153 - 2026-08-17

**Protocol**: Legacy AppState test resource ownership
**Status**: Complete

### Achievements

- Reproduced implicit `jarvis-terminal-worker-*` TemporaryDirectory cleanup in
  the two legacy AppState test classes and traced it to missing full lifecycle
  cleanup rather than a TerminalWorker production defect.
- Made all twelve local states register the existing idempotent
  `AppState.shutdown()` before assertions; FastAPI state persistence uses an
  owned `.test-fastapi-app-state-` directory that is removed after shutdown.
- Added a warning-enabled subprocess regression for both classes, preserving
  warning visibility and real default state composition without modifying
  production lifecycle code.

### Verification

- `python tests/run_all.py`: 654 total (652 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1600 total (1598 passed, 2 skipped)
- Warning-enabled AppState classes: 12/12 passed with no implicit TerminalWorker cleanup
- Ruff, compileall, Vitest 137, Playwright 7/1, typecheck, build, and required-services integration: passed

### Files Changed

- `tests/test_main_extended.py`
- `tests/test_main_fastapi_extended.py`
- `tests/test_run_all_coverage.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_153.md`
- `docs/reports/AUDIT_REPORT_143.md` (removed from rolling window)
- `docs/superpowers/plans/2026-08-17-app-state-test-resource-ownership.md`
- `docs/superpowers/specs/2026-08-17-app-state-test-resource-ownership-design.md`

---

## Iteration #152 - 2026-08-17

**Protocol**: Strict parent-owned Terminal Worker responses
**Status**: Complete

### Achievements

- Replaced permissive Terminal Worker response coercion with an exact
  eight-field JSON schema, built-in scalar types, finite non-negative duration,
  parseable timestamp, and consistent success/exit state.
- Kept command ID and risk correlation parent-owned; mismatches, missing or
  unknown fields, duplicate keys, non-finite constants, and excessive nesting
  now return the existing unsuccessful result instead of entering audit state
  or escaping as a decoder exception.
- Added TDD regressions covering eleven initially accepted malformed values and
  a separately reproduced 5,000-level recursion failure while preserving real
  fixed-operation child execution.

### Verification

- `python tests/run_all.py`: 654 total (652 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1599 total (1597 passed, 2 skipped)
- Focused terminal tests: 37/37 passed
- Ruff, compileall, Vitest 137, Playwright 7/1, typecheck, build, and required-services integration: passed

### Files Changed

- `src/core/kernel/terminal_worker.py`
- `tests/test_terminal_worker.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_152.md`
- `docs/reports/AUDIT_REPORT_142.md` (removed from rolling window)
- `docs/superpowers/plans/2026-08-17-terminal-worker-response-protocol.md`
- `docs/superpowers/specs/2026-08-17-terminal-worker-response-protocol-design.md`

---

## Iteration #151 - 2026-08-17

**Protocol**: Aggregate performance scratch ownership
**Status**: Complete

### Achievements

- Replaced the fixed `.test-perf` benchmark directory and recursive deletion with an owned `.test-perf-` `TemporaryDirectory`.
- Added a real behavioral regression for cleanup and exception-safe cwd restoration without changing MemoryStore or the benchmark workload.

### Verification

- `python tests/run_all.py`: 652 total (650 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1597 total (1595 passed, 2 skipped)
- Ruff, compileall, Vitest 137, Playwright 7/1, typecheck, build, and required-services integration: passed

### Files Changed

- `tests/run_all.py`
- `tests/test_run_all_coverage.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_151.md`
- `docs/reports/AUDIT_REPORT_141.md` (removed from rolling window)
- `docs/superpowers/plans/2026-08-17-aggregate-performance-temp-ownership.md`
- `docs/superpowers/specs/2026-08-17-aggregate-performance-temp-ownership-design.md`

---

## Iteration #150 - 2026-08-17

**Protocol**: Universal hash-enforced Python dependency lock
**Status**: Complete

### Achievements

- Added one `requirements.lock` containing 34 universal exact package blocks,
  with SHA-256 hashes and bounded environment markers, generated by the fixed
  `uv==0.12.5` Python 3.10 command.
- Made both Python CI jobs install the lock with `--require-hashes`; the
  contract job installs the repository separately with `--no-deps
  --no-build-isolation`, preventing a second floating dependency or build
  environment.
- Declared `setuptools.build_meta`, locked setuptools as development/build
  tooling, and added the `tomli` fallback required by repository tests on
  Python 3.10 while retaining `tomllib` on Python 3.11+.
- Added fail-closed offline guards for direct dependency coverage, exact pin
  uniqueness, per-block hashes, universal markers, forbidden sources,
  malformed top-level lines, generator drift, and CI bypass commands.
- Verified a clean CPython 3.10.21 hash install, editable build without build
  isolation, direct runtime imports, `pip check`, and the lock-pinned Ruff.

### Verification

- `python tests/run_all.py`: 652 total (650 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1596 total (1594 passed, 2 skipped)
- CPython 3.10.21 isolated `pip install --require-hashes -r requirements.lock`: passed
- Isolated `pip install --no-deps --no-build-isolation -e .`: passed without build dependency installation
- Isolated direct imports and `python -m pip check`: passed
- `python -m compileall -q src tests scripts`: passed
- `python -m ruff check src tests scripts`: passed with locked Ruff 0.16.3 and zero findings
- `cd frontend; npm test -- --run`: 137/137 passed
- `cd frontend; JARVIS_E2E_PORT=5174 npm run test:e2e`: 7 passed, 1 skipped by project condition
- `cd frontend; npm run typecheck`: passed
- `cd frontend; npm run build`: passed
- `python scripts/ci_local_integration.py --require-services`: passed
- `git diff --check`: passed

### Scope Boundary

This iteration changes dependency resolution, CI setup, repository tests, and
documentation only. It does not change runtime behavior, APIs, authorization,
Worker execution, Plugin policy, frontend behavior, the Python 3.10 floor, or
the package metadata lower-bound strategy. Python, pip, and the editable
project itself remain outside the third-party lock.

### Files Changed

- `.github/workflows/ci.yml`
- `requirements.lock`
- `pyproject.toml`
- `README.md`
- `docs/SETUP.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `tests/test_python_dependency_lock.py`
- `tests/test_project_config.py`
- `tests/test_ci_workflow.py`
- `tests/test_docs_setup.py`
- `tests/test_readme.py`
- `tests/run_all.py`
- `tests/test_run_all_coverage.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_150.md`
- `docs/reports/AUDIT_REPORT_140.md` (removed from rolling window)
- `docs/superpowers/plans/2026-08-17-python-dependency-lock.md`
- `docs/superpowers/specs/2026-08-17-python-dependency-lock-design.md`

---

## Iteration #149 - 2026-08-17

**Protocol**: Repository-wide Ruff zero baseline
**Status**: Complete

### Achievements

- Cleared the repository's 153 existing Ruff E/F/I/W findings without
  `--unsafe-fixes`, global suppressions, or runtime behavior changes.
- Applied 97 non-overlapping safe fixes, then resolved the remaining unused
  assignments, duplicate dictionary key, and assigned lambda explicitly.
- Limited E402 suppression to four standalone path-bootstrap modules and
  documented why project-local imports must follow their `sys.path` setup.
- Preserved public imports, monkeypatch targets, optional platform behavior,
  process ownership, and all prior mixed-worktree changes during self-review.
- Added Ruff to the declared development dependencies and established the
  unchanged CI command as a zero-finding gate.

### Verification

- `python tests/run_all.py`: 641 total (639 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1584 total (1582 passed, 2 skipped)
- `python -m compileall -q src tests scripts`: passed
- `python -m ruff check src tests scripts`: passed with zero findings
- `cd frontend; npm test -- --run`: 137/137 passed
- `cd frontend; JARVIS_E2E_PORT=5174 npm run test:e2e`: 7 passed, 1 skipped by project condition
- `cd frontend; npm run typecheck`: passed
- `cd frontend; npm run build`: passed
- `python scripts/ci_local_integration.py --require-services`: passed
- `git diff --check`: passed

### Scope Boundary

This iteration does not enable unsafe lint rewrites, expand ignored rule sets,
change APIs or runtime policy, or reformat unrelated assets. Existing E501 and
targeted handler-name exceptions remain unchanged; the four new E402 file
directives cover only required standalone import bootstrap boundaries.

### Files Changed

- `pyproject.toml`
- `src/`
- `tests/`
- `scripts/`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_149.md`
- `docs/reports/AUDIT_REPORT_139.md` (removed from rolling window)
- `docs/superpowers/plans/2026-08-17-ruff-zero-baseline.md`
- `docs/superpowers/specs/2026-08-17-ruff-zero-baseline-design.md`

---

## Iteration #148 - 2026-08-17

**Protocol**: Trusted role-tool capability assembly
**Status**: Complete

### Achievements

- Added an immutable five-entry role-tool catalog and strict assembly evidence
  containing only schema version, exact sorted capability IDs, and a canonical
  catalog SHA-256.
- Added public `role_tool` capability records and fail-closed registry assembly
  validation for missing, extra, duplicate, disabled, degraded, higher-risk,
  unverified, and digest-mismatched records.
- Required default production Role Workers to validate service-owned registry
  evidence against their local static catalog before binding fixed handlers;
  ordinary `AgentFactory` instances retain an empty broker.
- Self-review tightened the wire parser to exact built-in dict/list/string
  types, so Python container or scalar subclasses and tuple-shaped IDs cannot
  bypass the canonical JSON evidence contract.
- Upgraded the shared OpenAPI contract to `1.17.0` and extended the read-only
  Plugins view with role-tool counts, labels, and icons without adding any
  lifecycle or execution action.
- Preserved all existing role grants, tool budgets, redaction, audit, Skill,
  Plugin, UI component, terminal, and generic orchestrator boundaries.

### Verification

- `python tests/run_all.py`: 641 total (639 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1584 total (1582 passed, 2 skipped)
- `python -m compileall -q src tests scripts`: passed
- `cd frontend; npm test -- --run`: 137/137 passed
- `cd frontend; JARVIS_E2E_PORT=5174 npm run test:e2e`: 7 passed, 1 skipped by project condition
- `cd frontend; npm run typecheck`: passed
- `cd frontend; npm run build`: passed
- `python scripts/ci_local_integration.py --require-services`: passed
- `python -m ruff check src tests scripts`: 153 existing workspace findings (98 auto-fixable); new catalog and focused test clean
- `git diff --check`: passed

### Scope Boundary

Capability records describe inventory and never carry callables, handler
configuration, grants, commands, paths, or request-selected tool names. This
iteration does not expand the fixed five-tool catalog, add HTTP mutation, give
non-production factories a broker, or add OS-level filesystem/network
isolation.

### Files Changed

- `src/core/contracts/role_tool_catalog.py`
- `src/core/kernel/capability_manifest.py`
- `src/core/kernel/capability_registry.py`
- `src/core/brain/read_only_role_tools.py`
- `src/core/brain/role_worker.py`
- `src/main.py`
- `src/main_fastapi.py`
- `contracts/core-api.openapi.json`
- `frontend/src/types/api.ts`
- `frontend/src/views/PluginsView.tsx`
- `frontend/src/tests/domain-views.test.tsx`
- `tests/test_role_tool_catalog.py`
- `tests/test_capability_registry.py`
- `tests/test_capability_resolver.py`
- `tests/test_read_only_role_tools.py`
- `tests/test_role_worker.py`
- `tests/test_main.py`
- `tests/test_main_fastapi.py`
- `tests/test_api_contract.py`
- `tests/run_all.py`
- `tests/test_run_all_coverage.py`
- `README.md`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_148.md`
- `docs/reports/AUDIT_REPORT_138.md` (removed from rolling window)
- `docs/superpowers/plans/2026-08-17-role-tool-capability-assembly.md`
- `docs/superpowers/specs/2026-08-17-role-tool-capability-assembly-design.md`

---

## Iteration #147 - 2026-08-17

**Protocol**: Explicit in-process orchestrator registration
**Status**: Complete

### Achievements

- Added `Orchestrator.register_in_process(name, handler, capabilities=None)`
  for explicit thread-backed execution of closures, bound methods, callable
  instances, and other process-local handlers.
- Kept `register()` source-compatible and chainable while emitting a
  `DeprecationWarning` that names `register_worker()` for stable importable
  top-level functions and `register_in_process()` for intentional local
  execution. The wrapper never changes execution mode.
- Migrated `AgentFactory` and maintained thread-path tests to the explicit API;
  retained one compatibility regression proving parent-process execution and
  unchanged result behavior.
- Preserved declared/Worker paths, cancellation and timeout quarantine,
  public result/API contracts, and all unrelated prior worktree changes.

### Verification

- `python tests/run_all.py`: 626 total (624 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1569 total (1567 passed, 2 skipped)
- `python -m unittest tests.test_orchestrator tests.test_orchestrator_extended tests.test_orchestrator_extended_v2 tests.test_orchestrator_retry tests.test_api_contract -v`: 171/171 passed
- `python -m compileall -q src tests scripts`: passed
- `cd frontend; npm test -- --run`: 137/137 passed
- `cd frontend; npm run test:e2e`: 7 passed, 1 skipped by project condition
- `cd frontend; npm run typecheck`: passed
- `cd frontend; npm run build`: passed
- `python scripts/ci_local_integration.py --require-services`: passed
- `python -m ruff check src tests scripts`: existing workspace lint backlog remains; no new lint category from this change
- `git diff --check`: passed

### Scope Boundary

Closures, bound instances, and callable objects remain supported only through
the explicit in-process path. `register()` is deprecated but not removed.
Generic registration/cancellation is not exposed over HTTP, and no generic task
persistence or OS-level sandboxing is added.

### Files Changed

- `src/core/brain/orchestrator.py`
- `src/core/brain/agent_factory.py`
- `tests/test_orchestrator.py`
- `tests/test_orchestrator_extended.py`
- `tests/test_orchestrator_extended_v2.py`
- `tests/test_orchestrator_retry.py`
- `tests/test_api_contract.py`
- `README.md`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_147.md`
- `docs/reports/AUDIT_REPORT_137.md` (removed from rolling window)
- `docs/superpowers/plans/2026-08-17-explicit-in-process-registration.md`
- `docs/superpowers/specs/2026-08-17-explicit-in-process-registration-design.md`

---

## Iteration #146 - 2026-08-17

**Protocol**: Importable callable generic orchestrator Worker
**Status**: Complete

### Achievements

- Added internal `Orchestrator.register_worker(name, handler, capabilities=None)`
  for exact top-level functions whose module already binds the callable. The
  parent derives the locator; lambdas, closures, bound methods, callable
  instances, and `__main__` functions fail before registry mutation.
- Reused `RoleWorkerSupervisor` for child execution, bounded JSON task
  transport, output limits, timeout termination, and confirmation. Ordinary
  values and `AgentResult` returns preserve the generic result shape in the
  parent.
- Added internal `Orchestrator.cancel(agent_name, task_id)`. Cancellation is
  reported only after confirmed process termination, and parent dispatch owns
  exactly one `cancelled` history entry.
- Preserved HTTP/OpenAPI, Plugin and role Worker contracts, as well as legacy
  arbitrary callable registration and its thread quarantine behavior.
- Hardened the live API contract harness so loopback requests bypass ambient
  system proxies. Non-JSON startup errors remain retryable, and proxy-owned
  keep-alive sockets can no longer block HTTPServer cleanup.

### Verification

- `python tests/run_all.py`: 625 total (623 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1568 total (1566 passed, 2 skipped)
- `python -m unittest tests.test_orchestrator tests.test_orchestrator_extended tests.test_orchestrator_extended_v2 tests.test_orchestrator_retry -v`: 140/140 passed
- `python -m compileall -q src tests scripts`: passed
- `cd frontend; npm test -- --run`: 137/137 passed
- `cd frontend; npm run test:e2e`: 7 passed, 1 skipped by project condition
- `cd frontend; npm run typecheck`: passed
- `cd frontend; npm run build`: passed
- `python scripts/ci_local_integration.py --require-services`: passed
- `python -m ruff check src tests scripts`: existing workspace lint backlog remains; changed Worker source and fixture are clean
- `git diff --check`: passed

### Scope Boundary

Closures, bound instances, and callable objects remain on the explicit
in-process compatibility path. Generic Worker registration/cancellation is not
exposed over HTTP, and no generic task persistence or OS-level sandboxing is
added.

### Files Changed

- `src/core/brain/orchestrator.py`
- `src/core/brain/orchestrator_worker.py`
- `tests/orchestrator_worker_fixtures.py`
- `tests/test_orchestrator_extended_v2.py`
- `tests/test_api_contract.py`
- `tests/run_all.py`
- `tests/test_run_all_coverage.py`
- `README.md`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_146.md`
- `docs/reports/AUDIT_REPORT_136.md` (removed from rolling window)
- `docs/superpowers/specs/2026-08-17-importable-callable-worker-design.md`
- `docs/superpowers/plans/2026-08-17-importable-callable-worker.md`

---

## Iteration #145 - 2026-08-11

**Protocol**: Declarative generic orchestrator Worker boundary
**Status**: Complete

### Achievements

- Added internal `Orchestrator.register_declared()` registration for canonical
  Agent names and static module-local runner IDs. The first `echo` runner is a
  deterministic process-isolation bootstrap and cannot be selected through an
  HTTP request.
- Reused the existing spawn-safe `RoleWorkerSupervisor` and protocol for
  parent-owned child process lifecycle, bounded output, timeout termination,
  confirmation, and cleanup. Full generic task data crosses the boundary as
  strict, byte-bounded JSON; recursive values, invalid Unicode, non-string
  keys, non-finite numbers, duplicate child keys, and oversized data fail
  closed before execution. Boundary preflight accepts only exact built-in
  task scalars and JSON containers, so hostile subclasses cannot execute
  `__class__`, `__str__`, iteration, mapping, hash, or repr hooks.
- Preserved the public generic `AgentResult` schema and caller task ID, mapped
  confirmed Worker terminal states to existing counters/retry behavior, and
  kept unconfirmed Worker execution, including post-submit transport failures,
  fail-closed against reuse, unregister, and replacement.
- Preserved `register(callable)` as the documented in-process compatibility
  path, including Iteration 144 daemon-thread timeout quarantine; no adapter,
  OpenAPI contract, Plugin authority, or role Worker behavior changed.
- Added real spawn regressions for child PID execution, static runner
  rejection, strict JSON rejection, timeout/retry, unconfirmed lifecycle
  guards, and legacy callable compatibility. Rejected pre-execution input no
  longer leaves the logical Agent unavailable, and the tests are registered
  exactly once in the canonical aggregate suite.
- Self-review fixed declared retry exhaustion so a declared timeout retains
  exactly one original history entry even if the registry changes after the
  attempt. It also hardened static runner validation and task preflight
  against hostile Python subclasses without changing the legacy callable path.
- Moved Plugin Worker process startup to the trusted runtime directory and
  passed its already-validated Plugin root through a fixed internal argument.
  The child enters that root only for lifecycle work, preserving relative
  Plugin paths while avoiding Windows' transient cwd-handle race when reader
  startup fails.
- Declared `ruff>=0.8.0` in `.[dev]`, added a configuration regression, and
  restored the documented lint command through an isolated reachable mirror.
  The full check exposes a separately scoped remaining lint backlog; the Plugin
  Worker cwd-repair files add no lint category relative to `HEAD`.

### Verification

- `python tests/run_all.py`: 613 total (611 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1555 total (1553 passed, 2 skipped)
- `python -m compileall -q src tests scripts`: passed
- `cd frontend; npm test -- --run`: 137/137 passed
- `cd frontend; npm run test:e2e`: 7 passed, 1 skipped by project condition
- `cd frontend; npm run typecheck`: passed
- `cd frontend; npm run build`: passed
- `python scripts/ci_local_integration.py --require-services`: passed
- `python -m ruff check src tests scripts`: completed; 152 current-workspace
  E/F/I/W findings (98 auto-fixable). The five Plugin Worker cwd-repair files
  match their eight `HEAD` rule/file lint categories and introduce no new lint
  issue; the new Worker module is lint-clean.
- `git diff --check`: passed

### Files Changed

- `src/core/brain/orchestrator.py`
- `src/core/brain/orchestrator_worker.py`
- `tests/test_orchestrator_extended_v2.py`
- `src/adapters/subprocess_plugin_runtime.py`
- `src/runtime/plugin_worker.py`
- `tests/test_subprocess_plugin_runtime.py`
- `tests/test_plugin_worker_entrypoint.py`
- `pyproject.toml`
- `tests/test_project_config.py`
- `tests/run_all.py`
- `tests/test_run_all_coverage.py`
- `docs/superpowers/specs/2026-08-11-declarative-orchestrator-worker-design.md`
- `docs/superpowers/plans/2026-08-11-declarative-orchestrator-worker.md`
- `README.md`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_145.md`
- `docs/reports/AUDIT_REPORT_135.md`

---

## Iteration #144 - 2026-08-11

**Protocol**: Generic orchestrator timeout-quarantine lifecycle
**Status**: Complete

### Achievements

- Added a private join-deadline timeout path that quarantines a still-running
  generic orchestrator handler until its daemon thread exits naturally.
- Made registry lookup, dispatch assignment, retry reset, unregister,
  re-registration, and shutdown decisions lock-protected so a running Agent
  cannot be reused, removed, or replaced while its execution identity is
  unresolved.
- Preserved public timeout accounting and recovery behavior: every join timeout
  increments `AgentInfo.errors_count` once, while a handler-raised
  `TimeoutError` remains non-recoverable through `recover_agent()` and
  retryable through `dispatch_with_retry()`.
- Added deterministic event-driven regressions for timeout quarantine,
  retry/busy/reset races, registration replacement, unregister/dispatch
  interleaving, error accounting, handler timeout semantics, and shutdown.
- Updated current architecture documentation and rolling audit evidence without
  changing HTTP routes, OpenAPI shapes, Plugin authority, or role Worker paths.

### Verification

- `python tests/run_all.py`: 584 total (582 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1524 total (1522 passed, 2 skipped)
- `python -m compileall -q src tests scripts`: passed
- `cd frontend; npm test -- --run`: 137/137 passed
- `cd frontend; npm run test:e2e`: 7 passed, 1 skipped by project condition
- `cd frontend; npm run typecheck`: passed
- `cd frontend; npm run build`: passed
- `python scripts/ci_local_integration.py --require-services`: passed
- `git diff --check`: passed

### Files Changed

- `src/core/brain/orchestrator.py`
- `tests/test_orchestrator_extended_v2.py`
- `tests/run_all.py`
- `tests/test_run_all_coverage.py`
- `docs/superpowers/specs/2026-08-11-generic-orchestrator-timeout-quarantine-design.md`
- `docs/superpowers/plans/2026-08-11-generic-orchestrator-timeout-quarantine.md`
- `README.md`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_144.md`
- `docs/reports/AUDIT_REPORT_134.md`

---

## Iteration #143 - 2026-08-11

**Protocol**: Plugin Worker direct integer serialization boundary
**Status**: Complete

### Achievements

- Reproduced the direct-record path that allowed arbitrary Python integers past
  V1 validation and could expose the interpreter's raw integer-conversion
  `ValueError` during canonical JSON serialization.
- Added a shared 512-decimal-digit resource boundary for JSON payloads and
  positive protocol numeric fields, so direct construction and generic
  serialization fail through `PluginWorkerProtocolError` before freezing or
  encoding.
- Preserved V1 canonical encoding, Worker/Broker lifecycle ownership, Plugin
  permissions, HTTP shapes, and the existing wire-decoding boundary.
- Added regression coverage for in-limit round trips, positive and negative
  oversized JSON values, and oversized `pid`/`generation` fields.

### Verification

- `python tests/run_all.py`: 575 total (573 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1514 total (1512 passed, 2 skipped)
- `python -m compileall -q src tests scripts`: passed
- `cd frontend; npm test -- --run`: 137/137 passed
- `cd frontend; npm run test:e2e`: 7 passed, 1 skipped by project condition
- `cd frontend; npm run typecheck`: passed
- `cd frontend; npm run build`: passed
- `python scripts/ci_local_integration.py --require-services`: passed
- `git diff --check`: passed

### Files Changed

- `src/core/contracts/plugin_worker_protocol.py`
- `tests/test_plugin_worker_protocol.py`
- `docs/superpowers/specs/2026-08-11-plugin-worker-integer-boundary-design.md`
- `docs/superpowers/plans/2026-08-11-plugin-worker-integer-boundary.md`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_143.md`
- `docs/reports/AUDIT_REPORT_133.md`

---

## Iteration #142 - 2026-08-10

**Protocol**: Plugin Worker protocol recursion and resource-boundary hardening
**Status**: Complete

### Achievements

- Reproduced an unbounded `RecursionError` in the Iteration 141 baseline when
  deeply nested Broker arguments reached immutable message construction.
- Added an explicit JSON nesting limit before recursive freezing and normalized
  parser recursion and integer resource-limit failures into the stable
  `PluginWorkerProtocolError` boundary.
- Added regression coverage for deeply nested wire input, direct record
  construction, oversized JSON numbers, bounded diagnostics, and the absence of
  raw recursion details.
- Re-audited Worker/Broker output, call, byte, event, timeout, termination,
  request-field, ownership, and event-commit boundaries without adding a
  dependency or expanding HTTP authority.

### Verification

- `python tests/run_all.py`: 574 total (572 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1513 total (1511 passed, 2 skipped)
- `python -m compileall -q src tests scripts`: passed
- `cd frontend; npm test -- --run`: 137/137 passed
- `cd frontend; npm run test:e2e`: 7 passed, 1 skipped by project condition
- `cd frontend; npm run typecheck`: passed
- `cd frontend; npm run build`: passed
- `python scripts/ci_local_integration.py --require-services`: passed
- `git diff --check`: passed

### Files Changed

- `src/core/contracts/plugin_worker_protocol.py`
- `tests/test_plugin_worker_protocol.py`
- `docs/superpowers/plans/2026-08-07-iteration-142-hardening.md`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_142.md`
- `docs/reports/AUDIT_REPORT_132.md`

---

## Iteration #141 - 2026-08-04

**Protocol**: Worker-isolated Python Plugin runtime and service-owned lifecycle
**Status**: Complete

### Achievements

- Added a versioned Plugin Worker protocol, a default-deny parent Broker, and
  a persistent subprocess runtime that validates transport, bounds output and
  lifecycle calls, and confirms Worker termination before ownership is released.
- Migrated both repository Plugins to `python_worker`; Plugin imports and
  lifecycle hooks no longer enter the Core process. The V1 Broker permits only
  explicitly declared and granted `event.emit` delivery to the parent EventBus.
- Replaced production Python HTTPServer and FastAPI references to the legacy
  global Plugin manager with AppState-owned `PluginManager` and `EventBus`
  instances. Service shutdown now closes all Plugin Workers before the EventBus
  is destroyed, including after an earlier cleanup failure.
- Upgraded the shared OpenAPI contract to `1.16.0`, documented Worker-isolated
  Plugin behavior, and declared the existing load/enable/disable shapes without
  adding caller-controlled Worker fields or new lifecycle authority.
- Updated current architecture, setup guidance, and rolling audit evidence;
  the remaining Stage E limitation is same-user process isolation rather than
  OS-level filesystem or network sandboxing.

### Verification

- `python tests/run_all.py`: 572 total (570 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1511 total (1509 passed, 2 skipped)
- `python -m compileall -q src tests scripts`: passed
- `cd frontend; npm test -- --run`: 136/136 passed
- `cd frontend; npm run test:e2e`: 7 passed, 1 skipped by project condition
- `cd frontend; npm run typecheck`: passed
- `cd frontend; npm run build`: passed
- `python scripts/ci_local_integration.py --require-services`: passed

### Files Changed

- `src/core/contracts/plugin_worker_protocol.py`
- `src/core/kernel/event_bus.py`
- `src/core/kernel/plugin_api.py`
- `src/core/kernel/plugin_broker.py`
- `src/core/kernel/plugin_sdk.py`
- `src/runtime/__init__.py`
- `src/runtime/plugin_worker.py`
- `src/adapters/__init__.py`
- `src/adapters/subprocess_plugin_runtime.py`
- `plugins/event-logger/manifest.json`
- `plugins/event-logger/plugin.py`
- `plugins/plugin-template/manifest.json`
- `plugins/plugin-template/plugin.py`
- `src/main.py`
- `src/main_fastapi.py`
- `contracts/core-api.openapi.json`
- `frontend/server.js`
- `frontend/server.test.js`
- `tests/test_plugin_worker_protocol.py`
- `tests/test_plugin_broker.py`
- `tests/test_plugin_worker_entrypoint.py`
- `tests/test_subprocess_plugin_runtime.py`
- `tests/test_plugin_sdk.py`
- `tests/test_plugin_sdk_extended.py`
- `tests/test_plugin_sdk_extended_v2.py`
- `tests/test_plugin_installation.py`
- `tests/test_main.py`
- `tests/test_main_extended.py`
- `tests/test_main_fastapi.py`
- `tests/test_api_contract.py`
- `tests/test_readme.py`
- `tests/run_all.py`
- `tests/test_run_all_coverage.py`
- `README.md`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_141.md`
- `docs/reports/AUDIT_REPORT_131.md`
- `docs/superpowers/specs/2026-08-02-plugin-worker-runtime-design.md`
- `docs/superpowers/plans/2026-08-02-plugin-worker-runtime.md`

---

## Iteration #140 - 2026-07-31

**Protocol**: Express-only Git API contract and OpenAPI boundary
**Status**: Complete

### Achievements

- Upgraded the shared OpenAPI contract to `1.15.0` and declared
  `/api/git/status`, `/api/git/log`, and `/api/git/branches` as Express-only
  through path-level `x-jarvis-implementations`.
- Added Git status, changed-file, commit, log, and branches response schemas
  plus the shared `500` ErrorResponse contract without changing Express Git
  behavior.
- Added a typed `gitBranches` client method and Vitest coverage for all three
  Git read-only endpoints; Express server tests now cover all Git error paths.
- Updated README, development guide, project analysis, report index, AGENTS,
  and iteration-ledger counts so the machine-readable boundary and current
  evidence stay aligned.

### Verification

- `python -m unittest tests.test_api_contract.TestSharedApiContract -v`: 27/27 passed
- `python tests/run_all.py`: 513 total (511 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1384 total (1382 passed, 2 skipped)
- `python -m compileall -q src tests scripts`: passed
- `cd frontend; npm test -- --run`: 136/136 passed
- `cd frontend; JARVIS_E2E_PORT=5189; npm run test:e2e`: 7 passed, 1 skipped by project condition
- `cd frontend; npm run typecheck`: passed
- `cd frontend; npm run build`: passed
- `python scripts/ci_local_integration.py --require-services`: passed
- `git diff --check`: passed

### Files Changed

- `contracts/core-api.openapi.json`
- `tests/test_api_contract.py`
- `tests/run_all.py`
- `tests/test_run_all_coverage.py`
- `frontend/server.test.js`
- `frontend/src/services/jarvis-api.ts`
- `frontend/src/types/api.ts`
- `frontend/src/tests/jarvis-api.test.ts`
- `README.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_140.md`
- `docs/reports/AUDIT_REPORT_130.md`
- `AGENTS.md`
- `CHANGELOG.md`

---

## Iteration #139 - 2026-07-31

**Protocol**: Read-only capability registry contract and operational Plugins view
**Status**: Complete

### Achievements

- Added shared OpenAPI `1.14.0` coverage for `GET /api/capabilities/registry`, including bounded scalar query parameters, explicit public capability schemas, repository-relative path constraints, and stable invalid/unavailable errors.
- Added one shared capability query parser and response shaper, then wired repository-root-only discovery and deterministic resolution into Python HTTPServer and FastAPI without accepting caller-controlled roots or lifecycle mutations.
- Hardened the registry after independent review with a shared Plugin API version, real first-party compatibility coverage, a two-second single-flight snapshot cache, per-kind child bounds, bounded discovery issues, and a record-only public wire shape without resolver scores.
- Added an Express Core API proxy that preserves the original registry query and Core status/error envelope; no archive upload, URL fetch, install, enable, rollback, or removal endpoint was introduced.
- Added strict TypeScript capability records, a Core-gated polling client, and a read-only Plugins view inventory for kind counts, lifecycle, provenance, compatibility, health, risk, permissions, and relative origin metadata while preserving existing Plugin lifecycle actions.
- Covered loading, degraded, issue-only, empty, unavailable, and lifecycle states in Vitest, and added Playwright desktop/mobile evidence that capability metadata remains visible without overlap or horizontal overflow at 1440px and 390px.
- Completed Stage D while keeping package content local, disabled, unimported, unexecuted, and unavailable to HTTP mutation callers.

### Verification

- `python -m unittest tests.test_api_contract tests.test_capability_registry tests.test_capability_resolver tests.test_main tests.test_main_fastapi`: 394/394 passed
- `python tests/run_all.py`: 511 total (509 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1382 total (1380 passed, 2 skipped)
- `python -m compileall -q src tests scripts`: passed
- `cd frontend; npm test -- --run`: 135/135 passed
- `cd frontend; JARVIS_E2E_PORT=5189; npm run test:e2e`: 7 passed, 1 skipped by project condition
- `cd frontend; npm run typecheck`: passed
- `cd frontend; npm run build`: passed
- `python scripts/ci_local_integration.py --require-services`: passed
- `git diff --check`: passed

### Files Changed

- `contracts/core-api.openapi.json`
- `src/core/kernel/capability_api.py`
- `src/core/kernel/capability_registry.py`
- `src/core/kernel/capability_resolver.py`
- `src/core/kernel/plugin_sdk.py`
- `src/main.py`
- `src/main_fastapi.py`
- `frontend/server.js`
- `frontend/server.test.js`
- `frontend/src/types/api.ts`
- `frontend/src/services/jarvis-api.ts`
- `frontend/src/views/PluginsView.tsx`
- `frontend/src/styles/components.css`
- `frontend/src/tests/domain-views.test.tsx`
- `frontend/src/tests/jarvis-api.test.ts`
- `frontend/src/tests/polling-resource.test.ts`
- `frontend/e2e/command-center.spec.ts`
- `tests/test_api_contract.py`
- `tests/test_capability_registry.py`
- `tests/test_main.py`
- `tests/test_main_fastapi.py`
- `README.md`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_139.md`
- `docs/reports/AUDIT_REPORT_129.md`

---

## Iteration #138 - 2026-07-29

**Protocol**: Reversible disabled capability lifecycle with fail-closed drift detection
**Status**: Complete

### Achievements

- Added bounded immutable upgrades that publish content before atomically switching the selected revision; exact retries remain idempotent and a failed index replacement preserves the previous pointer.
- Added explicit and previous-revision rollback with full bundle, manifest, and payload revalidation before any state switch.
- Added canonical revision removal with tombstone restoration on index failure, deterministic fallback selection, last-revision uninstall, and preservation of unknown sibling content.
- Added restart-safe rebuild from the stored bundle and extracted payload, atomic `revision.json` repair, preservation of root-level operator files, and fail-closed rejection of changed or injected payload content.
- Serialized same-root writers with the existing shared `RLock`, bounded each capability to 64 revisions, and kept every installed or restored revision disabled.

### Verification

- `python -m unittest tests.test_file_capability_store -v`: 47/47 passed
- `python tests/run_all.py`: 500 total (498 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1357 total (1355 passed, 2 skipped)
- `python -m compileall -q src tests scripts`: passed
- `git diff --check`: passed

### Files Changed

- `src/adapters/file_capability_store.py`
- `tests/test_file_capability_store.py`
- `tests/run_all.py`
- `tests/test_run_all_coverage.py`
- `AGENTS.md`
- `README.md`
- `CHANGELOG.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_138.md`
- `docs/reports/AUDIT_REPORT_128.md`

---

## Iteration #137 - 2026-07-29

**Protocol**: Verified local package staging with disabled-only publication
**Status**: Complete

### Achievements

- Added a standard-library `FileCapabilityStore` for content-addressed local ZIP bundles without network access, imports, process creation, or automatic enablement.
- Enforced archive byte, entry-count, expanded-byte, and per-file limits before publication; rejected traversal, absolute/drive/backslash paths, symlinks, encrypted members, duplicate/conflicting entries, invalid encodings, unsupported compression, and malformed layouts.
- Required a strict manifest with HTTPS source, one of four allowlisted licenses, a valid payload entrypoint, and verified immutable public metadata that retains repository-relative POSIX paths only.
- Published verified revisions through temporary siblings and `os.replace`, retained disabled lifecycle state, failed closed on damaged state or reparse traversal, and made exact retries idempotent and failed publications retryable.
- Added regression coverage for malformed archives, manifest and license validation, Win32 aliases, state reload, atomic failure cleanup, storage identity aliasing, and all allowlisted licenses.

### Verification

- `python -m unittest tests.test_file_capability_store tests.test_capability_registry -v`: 48/48 passed
- `python tests/run_all.py`: 486 total (484 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1343 total (1341 passed, 2 skipped)
- `python -m compileall -q src tests scripts`: passed
- `git diff --check`: passed

### Files Changed

- `.gitignore`
- `src/adapters/file_capability_store.py`
- `src/core/kernel/capability_manifest.py`
- `tests/test_file_capability_store.py`
- `tests/test_capability_registry.py`
- `tests/run_all.py`
- `tests/test_run_all_coverage.py`
- `AGENTS.md`
- `README.md`
- `CHANGELOG.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_137.md`
- `docs/reports/AUDIT_REPORT_127.md`

---

## Iteration #136 - 2026-07-28

**Protocol**: Bounded compatibility evaluation and deterministic local resolution
**Status**: Complete

### Achievements

- Added a strict numeric compatibility grammar with exact and ordered comparators, at most eight clauses, bounded components, and explicit rejection of wildcards, caret ranges, prereleases, and malformed expressions.
- Added immutable runtime targets and capability queries with strict kind, risk, boolean, query-character, length, and `1..100` limit validation.
- Added deterministic local resolution with exact ID/name, token, and description scoring, health/compatibility/provenance/risk quality signals, and capability-ID tie breaking.
- Evaluated unsupported or unavailable runtimes as `unknown`, constraint mismatches as `incompatible`, and allowed callers to filter to proven-compatible results without mutating the registry snapshot.
- Verified the live repository query `memory` resolves only `skill:memory-keeper` with an explicit compatible status; no dependency or external service was introduced.

### Verification

- `python -m unittest tests.test_capability_registry tests.test_capability_resolver tests.test_run_all_coverage -v`: 38/38 passed
- `python tests/run_all.py`: 452 total (450 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1308 total (1306 passed, 2 skipped)
- `python -m compileall -q src tests scripts`: passed
- `git diff --check`: passed

### Files Changed

- `src/core/kernel/capability_resolver.py`
- `tests/test_capability_resolver.py`
- `tests/run_all.py`
- `tests/test_run_all_coverage.py`
- `AGENTS.md`
- `README.md`
- `CHANGELOG.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_136.md`
- `docs/reports/AUDIT_REPORT_126.md`

---

## Iteration #135 - 2026-07-28

**Protocol**: Versioned local capability records and read-only discovery
**Status**: Complete

### Achievements

- Started Stage D with immutable schema-version-1 records for Skill, Plugin, and UI component capabilities, including lifecycle, permissions, compatibility, provenance, health, risk, and public relative paths.
- Added deterministic repository-local discovery that scans only trusted direct roots, never imports plugin code, rejects symlinked capabilities, ignores generated artifacts, and computes bounded content digests.
- Preserved unknown version, source, and license metadata as explicit null/incomplete values instead of inventing provenance; malformed plugin manifests remain visible as invalid high-risk records.
- Discovered the current repository as 22 capability records: 19 Skills, 2 Plugins, and 1 directly exported UI component, with no snapshot-level scan errors.
- Registered the new 14-test suite exactly once in the canonical aggregate runner and recorded the Stage D design and five-iteration implementation plan.

### Verification

- `python -m unittest tests.test_capability_registry tests.test_run_all_coverage -v`: 27/27 passed
- `python tests/run_all.py`: 442 total (440 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1297 total (1295 passed, 2 skipped)
- `python -m compileall -q src tests scripts`: passed
- `git diff --check`: passed

### Files Changed

- `src/core/kernel/capability_manifest.py`
- `src/core/kernel/capability_registry.py`
- `tests/test_capability_registry.py`
- `tests/run_all.py`
- `tests/test_run_all_coverage.py`
- `docs/superpowers/specs/2026-07-28-capability-registry-safe-deployment-design.md`
- `docs/superpowers/plans/2026-07-28-capability-registry-safe-deployment.md`
- `AGENTS.md`
- `README.md`
- `CHANGELOG.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_135.md`
- `docs/reports/AUDIT_REPORT_125.md`

---

## Iteration #134 - 2026-07-28

**Protocol**: Bounded read-only model tools inside role Workers
**Status**: Complete

### Achievements

- Added strict role-tool protocol values, schema validation and explicit call, argument, result, total-output and elapsed-time budgets.
- Enabled model-driven tool calls only inside the production `RoleWorker`, with every invocation forced through the default-deny `RoleToolBroker` and recorded in a bounded redacted audit.
- Registered the fixed five-tool read-only catalog for system status, model inventory, orchestrator status, Memory search and repository metadata.
- Extended Ollama request/response and local fixture coverage for deterministic tool calls, while keeping terminal execution, Plugin lifecycle, HTTP capability tokens and generic `/api/orchestrator/dispatch` outside the capability.
- Registered the new suites exactly once, synchronized current project documentation, repaired the encoding of the Iteration 133 report and rolled the audit window to Iteration 125-134.

### Verification

- `python tests/run_all.py`: 428 total (426 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1282 total (1280 passed, 2 skipped)
- `python -m compileall -q src tests scripts`: passed
- `cd frontend; npm test -- --run`: 129/129 passed
- `cd frontend; JARVIS_E2E_PORT=5174; npm run test:e2e`: 5 passed, 1 skipped by project condition
- `cd frontend; npm run typecheck`: passed
- `cd frontend; npm run build`: passed
- `python scripts/ci_local_integration.py --require-services`: passed
- `git diff --check`: passed

### Files Changed

- `tests/run_all.py`
- `tests/test_run_all_coverage.py`
- `tests/test_agent_factory.py`
- `README.md`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_134.md`
- `docs/reports/AUDIT_REPORT_133.md`
- `docs/reports/AUDIT_REPORT_124.md`
- `docs/reports/AUDIT_REPORT_123.md`

---

## Iteration #133 - 2026-07-27

**Protocol**: Role task record persistence and orphan Worker reconciliation
**Status**: Complete

### Achievements

- Created `RoleTaskRecordRepository` for atomic JSON-file persistence of `WorkerTaskRecord` snapshots inside the auto-memory directory.
- Added `RoleWorkerSupervisor.recover_orphans()` that marks non-terminal persisted records as `CRASHED`, terminal-unconfirmed as `FAILED`, and preserves confirmed terminal records.
- Wired `_persist_role_tasks()` into `AppState.shutdown()` to capture active records before supervisor shutdown.
- Added orphan recovery to the FastAPI lifespan: loads persisted records after run-state recovery, reconciles orphans, logs count, and clears the file.

### Verification

- `python tests/run_all.py`: 352/352 (350 passed, 2 skipped)
- `python -m unittest tests.test_role_task_persistence -v`: 13/13 passed
- `python -m unittest tests.test_role_worker tests.test_role_dispatch_service -v`: 45/45 passed
- `python -m compileall -q src tests scripts`: passed

### Files Changed

- `src/adapters/role_task_record_repository.py` (new)
- `src/core/brain/role_worker.py`
- `src/main_fastapi.py`
- `tests/test_role_task_persistence.py` (new, 13 tests)
- `docs/reports/AUDIT_REPORT_133.md`
---
## Iteration #132 - 2026-07-26

**Protocol**: Terminable synchronous role dispatch migration
**Status**: Complete

### Achievements

- Migrated synchronous role, capability, and ordered batch dispatch through `RoleDispatchService` and the terminable `RoleWorkerSupervisor`, while preserving their compatibility response shapes and batch positions.
- Aligned Python HTTPServer, FastAPI, Express proxy budgets, OpenAPI descriptions, and stable Worker failure mappings for the three role routes.
- Kept `/api/orchestrator/dispatch` unchanged; role-task persistence/recovery and bounded model tool loops remain the next Phase 11 work.
- Added canonical aggregate coverage for the service and Python/FastAPI adapters, and made the browser E2E port isolatable with `JARVIS_E2E_PORT`.
- Closed final lifecycle review gaps for terminal observer delivery, nonterminal waiter notifications, HTTP bind-failure cleanup, and the environment-independent aggregate runner guard.

### Verification

- `python tests/run_all.py`: 352 total (350 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1225 total (1223 passed, 2 skipped)
- `python -m compileall -q src tests scripts`: passed
- `python scripts/ci_local_integration.py --require-services --timeout 15`: passed
- `cd frontend; npm test -- --run`: 129/129 passed
- `cd frontend; JARVIS_E2E_PORT=5174; npm run test:e2e`: 5 passed, 1 skipped by project condition
- `cd frontend; npm run typecheck`: passed
- `cd frontend; npm run build`: passed
- `python -m ruff check src tests scripts`: not run because Ruff is not installed in the project environment

### Files Changed

- `src/core/brain/role_worker.py`
- `src/main.py`
- `tests/test_main.py`
- `tests/test_role_worker.py`
- `tests/run_all.py`
- `tests/test_run_all_coverage.py`
- `README.md`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_132.md`
- `docs/reports/AUDIT_REPORT_122.md`
---

## Iteration #131 - 2026-07-21

**Protocol**: Atomic recovery publication and role-task lifecycle hardening
**Status**: Complete

### Achievements

- Changed `FileRunStateRepository` to publish immutable revision snapshots before atomically switching the authenticated active manifest.
- Serialized same-root readers and writers with a shared thread lock plus a Windows machine-wide named mutex or POSIX no-follow `flock`, then revalidated the active revision at publication time.
- Added an authenticated save-request fingerprint for exact committed-readback retries, recognized only canonical same-revision staging remnants for initial retry, and made authenticated archive publication idempotently retryable so an archived `run_id` cannot be reactivated as an interrupted save.
- Limited automatic snapshot cleanup to positive canonical revisions on POSIX descriptor-relative paths; Windows and platforms without the required primitives conservatively retain old revision and staging data, while unknown content is always preserved for inspection.
- Kept unconfirmed or record-less Worker runtimes resident and blocked only reuse of their role, preserved the first timeout/cancel intent, serialized process-handle termination and cleanup, and bounded public terminal history before cleanup completes.
- Moved blocking Worker submission and cancellation off the FastAPI event loop, rejected unsupported task fields, and stabilized spawn and terminal-race HTTP errors.
- Added the missing Express create/list/get/cancel proxies for `/api/roles/tasks` and regression coverage for their exact Core API forwarding behavior.
- Reported skipped Python tests separately from passed tests in console and JSON aggregate results, with ledger guards for total accounting.
- Kept legacy synchronous role dispatch, persistent task recovery, and model tool execution explicitly outside this iteration's guarantees.

### Verification

- `python -m unittest tests.test_file_run_state_repository tests.test_role_worker tests.test_main_fastapi.TestRoleTaskLifecycleEndpoints`: 52 total (50 passed, 2 skipped)
- `cd frontend; .\\node_modules\\.bin\\vitest.cmd run server.test.js`: 51/51 passed
- `python tests/run_all.py`: 295 total (293 passed, 2 skipped)
- `python -m unittest discover -s tests -p "test_*.py"`: 1170 total (1168 passed, 2 skipped)
- `python -m compileall -q src tests scripts`: passed
- `ruff check src tests scripts`: not run because Ruff is not installed in the project environment or `PATH`
- `cd frontend; npm test -- --run`: 113/113 passed
- `cd frontend; npm run test:e2e`: 5 passed, 1 skipped by project condition
- `cd frontend; npm run typecheck`: passed
- `cd frontend; npm run build`: passed
- `python scripts/ci_local_integration.py --require-services --timeout 15`: passed

### Files Changed

- `.gitignore`
- `README.md`
- `frontend/server.js`
- `frontend/server.test.js`
- `src/adapters/file_run_state_repository.py`
- `src/core/brain/role_worker.py`
- `src/main_fastapi.py`
- `tests/test_file_run_state_repository.py`
- `tests/test_main_fastapi.py`
- `tests/test_role_worker.py`
- `tests/test_iteration_ledger.py`
- `tests/test_run_all_coverage.py`
- `tests/worker_fixtures.py`
- `tests/run_all.py`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_131.md`
- `docs/reports/AUDIT_REPORT_121.md`
- `AGENTS.md`
- `CHANGELOG.md`

---

## Iteration #130 - 2026-07-19

**Protocol**: Terminable asynchronous role-task lifecycle
**Status**: Complete

### Achievements

- Added protocol-version-1 Worker requests, events, terminal states, strict serialization, and confirmed-termination invariants.
- Added a parent-authoritative, Windows-spawn-compatible role Worker supervisor with timeout, cancellation, crash, late-event, bounded-output, bounded-history, and shutdown cleanup behavior.
- Added a fixed production runner that builds child-local Ollama and AgentFactory dependencies and writes returned Token usage into the parent service telemetry.
- Added FastAPI create/list/get/cancel lifecycle endpoints without allowing HTTP callers to choose execution controls.
- Upgraded OpenAPI to `1.12.0` with Worker schemas, stable success/error responses, and conditional confirmation for timeout/cancelled records.
- Registered Worker protocol, supervisor, and API lifecycle coverage in the canonical aggregate suite.
- Kept legacy synchronous role dispatch unchanged and explicitly outside the new cancellation guarantee.

### Verification

- `python -m unittest tests.test_worker_protocol tests.test_role_worker tests.test_main_fastapi.TestRoleTaskLifecycleEndpoints tests.test_api_contract.TestSharedApiContract -v`: 40/40 passed
- `python -m unittest tests.test_role_worker tests.test_agent_factory tests.test_agent_factory_extended tests.test_ollama_manager tests.test_ollama_manager_extended`: 140/140 passed
- `python tests/run_all.py`: 262/262 passed
- `python -m unittest discover -s tests -p "test_*.py"`: 1136/1136 passed
- `python -m compileall -q src tests`: passed
- `cd frontend; npm test -- --run`: 112/112 passed
- `cd frontend; npm run test:e2e`: 5 passed, 1 skipped by project condition
- `cd frontend; npm run typecheck`: passed
- `cd frontend; npm run build`: passed
- `python scripts/ci_local_integration.py --require-services`: passed

### Files Changed

- `src/core/contracts/worker_protocol.py`
- `src/core/contracts/__init__.py`
- `src/core/brain/role_worker.py`
- `src/main_fastapi.py`
- `contracts/core-api.openapi.json`
- `tests/worker_fixtures.py`
- `tests/test_worker_protocol.py`
- `tests/test_role_worker.py`
- `tests/test_main_fastapi.py`
- `tests/test_api_contract.py`
- `tests/run_all.py`
- `tests/test_run_all_coverage.py`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_130.md`
- `docs/superpowers/specs/2026-07-19-role-worker-lifecycle-design.md`
- `docs/superpowers/plans/2026-07-19-role-worker-lifecycle.md`
- `CHANGELOG.md`

---

## Iteration #129 - 2026-07-16

**Protocol**: Authenticated context continuity and startup recovery
**Status**: Complete

### Achievements

- Added versioned immutable run state and concrete next-action contracts with monotonic revisions.
- Added context budget watermarks and deterministic Red-level checkpoint behavior.
- Added shared secret redaction, fixed-section resume documents, and an HMAC-authenticated atomic recovery repository.
- Added Git drift inspection and recovery coordination for Red context, changed HEAD/branch, partial work, and dirty paths.
- Integrated fail-closed one-time active-run recovery into FastAPI startup.
- Added a combined recovery gate covering Red context, dirty work, and a partial agent handoff.

### Verification

- `python -m unittest tests.test_run_state tests.test_context_budget tests.test_resume_document tests.test_file_run_state_repository tests.test_run_lifecycle tests.test_main_fastapi.TestRunRecoveryLifespan tests.test_phase_a_recovery ... -v`: 35/35 passed
- `python tests/run_all.py`: 262/262 passed in the final Iteration 130 branch verification
- `python -m unittest discover -s tests -p "test_*.py"`: 1136/1136 passed in the final Iteration 130 branch verification
- `python -m compileall -q src tests`: passed
- `cd frontend; npm test -- --run`: 112/112 passed
- `cd frontend; npm run test:e2e`: 5 passed, 1 skipped by project condition
- `cd frontend; npm run typecheck`: passed
- `cd frontend; npm run build`: passed
- `python scripts/ci_local_integration.py --require-services`: passed

### Files Changed

- `src/core/contracts/run_state.py`
- `src/core/brain/context_budget.py`
- `src/core/brain/resume_document.py`
- `src/core/kernel/secret_redaction.py`
- `src/adapters/file_run_state_repository.py`
- `src/adapters/git_workspace.py`
- `src/app/run_lifecycle.py`
- `src/main_fastapi.py`
- `tests/test_run_state.py`
- `tests/test_context_budget.py`
- `tests/test_resume_document.py`
- `tests/test_file_run_state_repository.py`
- `tests/test_run_lifecycle.py`
- `tests/test_phase_a_recovery.py`
- `tests/test_main_fastapi.py`
- `tests/run_all.py`
- `tests/test_run_all_coverage.py`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_129.md`
- `docs/superpowers/plans/2026-07-16-phase-a-context-continuity.md`
- `CHANGELOG.md`

---

## Iteration #128 - 2026-07-15

**Protocol**: Default-deny role tool authorization boundary
**Status**: Complete

### Achievements

- Added `RoleToolPolicy` for exact, explicit per-role grants with no wildcard or ambient fallback.
- Added `RoleToolBroker` as the only supported invocation choke point; profile declaration, grant, and registered handler must all match before execution.
- Added immutable decisions and a thread-safe bounded audit history with stable denial reasons.
- Changed `AgentFactory` prompts to expose only authorized tools and to state `[TOOL ACCESS] disabled` by default.
- Separated `declared_tools` from `authorized_tools` in task metadata and kept automatic model-driven tool invocation disabled.
- Evaluated Kontext CLI and Doberman Core, adopting their fail-closed/on-path principles without introducing another runtime or control plane.

### Verification

- `python -m unittest tests.test_role_tools tests.test_agent_factory tests.test_agent_factory_extended -v`: 68/68 passed
- `python tests/run_all.py`: 208/208 passed
- `python -m unittest discover -s tests -p "test_*.py"`: 1080/1080 passed
- `cd frontend; npm test -- --run`: 112/112 passed
- `cd frontend; npm run test:e2e`: 5 passed, 1 skipped by project condition
- `cd frontend; npm run typecheck`: passed
- `cd frontend; npm run build`: passed

### Files Changed

- `src/core/brain/role_tools.py`
- `src/core/brain/agent_factory.py`
- `tests/test_role_tools.py`
- `tests/test_agent_factory.py`
- `docs/superpowers/specs/2026-07-15-role-tool-authorization-design.md`
- `docs/superpowers/plans/2026-07-15-role-tool-authorization.md`
- `docs/reports/GITHUB_LEARNING_REPORT.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_128.md`
- `README.md`
- `docs/SETUP.md`
- `AGENTS.md`
- `CHANGELOG.md`

---

## Iteration #127 - 2026-07-15

**Protocol**: Recoverable role errors with timeout-safe state semantics
**Status**: Complete

### Achievements

- Distinguished completed handler errors from timeouts with an internal recoverable marker while preserving the public agent status contract.
- Added atomic orchestrator recovery that retains the failed result, history, counters, and statistics.
- Recovered role agents only for later independent requests; no hidden retry occurs.
- Kept timeout states nonrecoverable because their daemon handler thread may still be running.
- Verified an Ollama error followed by a successful request invokes the manager twice and leaves the role idle.

### Verification

- `python -m unittest tests.test_orchestrator tests.test_orchestrator_extended tests.test_orchestrator_extended_v2 tests.test_orchestrator_retry -v`: 93/93 passed
- `python -m unittest tests.test_agent_factory tests.test_agent_factory_extended tests.test_orchestrator tests.test_orchestrator_extended tests.test_orchestrator_extended_v2 tests.test_orchestrator_retry -v`: 154/154 passed
- `python tests/run_all.py`: 208/208 passed
- `python -m unittest discover -s tests -p "test_*.py"`: 1073/1073 passed
- `cd frontend; npm test -- --run`: 112/112 passed
- `cd frontend; npm run test:e2e`: 5 passed, 1 skipped by project condition
- `cd frontend; npm run typecheck`: passed
- `cd frontend; npm run build`: passed

### Files Changed

- `src/core/brain/orchestrator.py`
- `src/core/brain/agent_factory.py`
- `tests/test_orchestrator_extended.py`
- `tests/test_agent_factory.py`
- `docs/superpowers/specs/2026-07-15-role-error-recovery-design.md`
- `docs/superpowers/plans/2026-07-15-role-error-recovery.md`
- `docs/reports/GITHUB_LEARNING_REPORT.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_127.md`
- `AGENTS.md`
- `CHANGELOG.md`

---

## Iteration #126 - 2026-07-15

**Protocol**: Production Ollama role execution
**Status**: Complete

### Achievements

- Replaced production role placeholder responses with real Ollama-backed execution through the existing `AgentFactory` injection point.
- Added trusted `JARVIS_ROLE_MODEL` selection, stable upstream failure handling, and a corrected semantic role-selection call.
- Reused each service's single `OllamaManager`, so role calls contribute to the existing Token telemetry instead of creating a parallel client.
- Proved Python HTTPServer, FastAPI, and Express role dispatch return deterministic fixture content while preserving public request and response shapes.
- Kept role tools as prompt metadata only; terminal and plugin capability boundaries remain unchanged.

### Verification

- `python -m unittest tests.test_agent_factory tests.test_agent_factory_extended -v`: 60/60 passed
- `python -m unittest tests.test_main_extended.TestAppStateExtended tests.test_main_fastapi_extended.TestAppState tests.test_api_contract -v`: 30/30 passed
- `python tests/run_all.py`: 208/208 passed
- `python -m unittest discover -s tests -p "test_*.py"`: 1066/1066 passed
- `cd frontend; npm test -- --run`: 112/112 passed
- `cd frontend; npm run test:e2e`: 5 passed, 1 skipped by project condition
- `cd frontend; npm run typecheck`: passed
- `cd frontend; npm run build`: passed

### Files Changed

- `src/core/brain/agent_factory.py`
- `src/main.py`
- `src/main_fastapi.py`
- `tests/test_agent_factory.py`
- `tests/test_main_extended.py`
- `tests/test_main_fastapi_extended.py`
- `tests/test_api_contract.py`
- `README.md`
- `docs/SETUP.md`
- `docs/reports/GITHUB_LEARNING_REPORT.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_126.md`
- `docs/superpowers/specs/2026-07-15-production-role-execution-design.md`
- `docs/superpowers/plans/2026-07-15-production-role-execution.md`
- `AGENTS.md`
- `CHANGELOG.md`

---

## Iteration #125 - 2026-07-14

**Protocol**: Role routing parity across three service adapters
**Status**: Complete

### Achievements

- Implemented `GET /api/roles`, `GET /api/roles/{role_name}`, and all role dispatch routes in the Python HTTPServer.
- Unified FastAPI role validation and error envelopes with the shared adapter contract.
- Added Express Core API proxy coverage for role listing, role details, capability dispatch, and batch dispatch.
- Added shared OpenAPI `1.11.0` schemas for role profiles, dispatch results, and role request/response shapes.
- Standardized role errors as `ROLE_NOT_FOUND`, `CAPABILITY_NOT_FOUND`, and `INVALID_REQUEST`, including timeout defaults and bounds.
- Added handler, proxy, and live three-adapter contract regression coverage.

### Verification

- `python tests/run_all.py`: 208/208 passed
- `python -m unittest discover -s tests -p "test_*.py"`: 1058/1058 passed
- `python -m unittest tests.test_api_contract tests.test_main tests.test_main_fastapi`: 302/302 passed
- `cd frontend; npm test -- --run`: 112/112 passed
- `cd frontend; node --check server.js`: passed
- `git diff --check`: passed

### Files Changed

- `src/main.py`
- `src/main_fastapi.py`
- `frontend/server.js`
- `frontend/server.test.js`
- `tests/test_main.py`
- `tests/test_main_fastapi.py`
- `tests/test_api_contract.py`
- `contracts/core-api.openapi.json`
- `README.md`
- `AGENTS.md`
- `docs/reports/README.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/AUDIT_REPORT_125.md`

---

## Iteration #124 - 2026-07-13

**Protocol**: Orchestrator contract integrity and three-adapter dispatch evidence
**Status**: Complete

### Achievements

- Enforced the shared orchestrator history bound of `1..100` in FastAPI and documented `maximum: 100` in OpenAPI.
- Unified Python HTTPServer dispatch defaults and validation with FastAPI: `timeout=300`, `priority=1`, priority `0..3`.
- Added `maximum` support to the local contract shape validator.
- Extended the real loopback harness to dispatch through Python HTTPServer, FastAPI, and Express, validating complete `AgentResult` payloads and invalid-request envelopes.
- Completed the Express Core fixture with the required `error` and `duration_ms` fields.
- Upgraded the shared contract to OpenAPI `1.10.0`, declaring history/dispatch defaults, `timeout` range `1..300`, non-blank text fields, and dispatch `413` responses.
- Rejected malformed JSON extremes and unpaired Unicode surrogates without disconnecting; valid surrogate pairs are normalized to Unicode scalar values.
- Stabilized Python HTTPServer oversized-body responses on Windows with bounded chunked request draining before the `413` envelope.
- Added a two-second total deadline for in-limit HTTPServer request bodies so partial uploads cannot monopolize the single-threaded service.
- Kept role-specific routes explicitly outside the shared contract until their semantics are aligned across all adapters.

### Verification

- `python tests/run_all.py`: 189/189 passed
- `python -m unittest discover -s tests -p "test_*.py"`: 1020/1020 passed
- `python -m unittest tests.test_api_contract`: 18/18 passed
- `python -m unittest tests.test_main tests.test_main_fastapi`: 246/246 passed
- `python -m compileall -q src tests scripts`: passed
- `cd frontend; npm test -- --run`: 103/103 passed
- `git diff --check`: passed

### Files Changed

- `src/main.py`
- `src/main_fastapi.py`
- `tests/test_main.py`
- `tests/test_main_fastapi.py`
- `tests/test_api_contract.py`
- `contracts/core-api.openapi.json`
- `frontend/server.js`
- `frontend/server.test.js`
- `docs/superpowers/specs/2026-07-13-orchestrator-contract-integrity-design.md`
- `docs/superpowers/plans/2026-07-13-orchestrator-contract-integrity.md`
- `docs/reports/AUDIT_REPORT_124.md`

---

## Iteration #123 - 2026-07-13

**Protocol**: Shared orchestrator route contract across three service adapters
**Status**: Complete

### Achievements

- Added the shared `GET /api/orchestrator/agents`, `GET /api/orchestrator/history`, and `POST /api/orchestrator/dispatch` contract to OpenAPI `1.9.0` with agent, history, dispatch, and proxy error schemas.
- Added Express Core API proxy coverage and aligned Python HTTPServer/FastAPI history limits with the shared `1..100` query range.
- Extended the live three-service contract harness to validate orchestrator response schemas and proxy failure envelopes.

### Verification

- `python tests/run_all.py`: 166/166 passed
- `python -m unittest discover -s tests -p "test_*.py"`: 966/966 passed
- `python -m unittest tests.test_api_contract`: 16/16 passed
- `python -m compileall -q src tests scripts`: passed
- `cd frontend; npm test -- --run`: 80/80 passed
- `cd frontend; npm run test:e2e`: 5 passed, 1 skipped by project condition
- `cd frontend; npm run typecheck`: passed
- `cd frontend; npm run build`: passed
- `git diff --check`: passed

### Files Changed

- `contracts/core-api.openapi.json`
- `frontend/server.js`
- `frontend/server.test.js`
- `src/main.py`
- `tests/test_api_contract.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `docs/reports/GITHUB_LEARNING_REPORT.md`
- `docs/reports/PROJECT_ANALYSIS.md`
- `docs/reports/README.md`
- `docs/reports/AUDIT_REPORT_123.md`

---

## Iteration #122 - 2026-07-13

**Protocol**: Deterministic required-services integration gate
**Status**: Complete

### Achievements

- Added `scripts/local_ollama_fixture.py`, a repository-owned minimal Ollama HTTP fixture covering version, model inventory, process inventory, and streaming chat token frames.
- Added `scripts/ci_local_integration.py`, which allocates ephemeral loopback ports, starts FastAPI/Core, Express, and the fixture, runs `local_integration_profile.py --require-services`, and cleans up child processes and logs on Windows and POSIX hosts.
- Promoted the real-service profile into the GitHub Actions Python contract job without downloading models or depending on an external Ollama daemon.
- Added runner/fixture guard tests and documented the deterministic CI-equivalent command.

### Verification

- `python tests/run_all.py`: 165/165 passed
- `python -m unittest discover -s tests -p "test_*.py"`: 965/965 passed
- `python -m compileall -q src tests scripts`: passed
- `python scripts/ci_local_integration.py --require-services --timeout 15`: passed
- `cd frontend; npm test -- --run`: 79/79 passed
- `cd frontend; npm run typecheck`: passed
- `cd frontend; npm run build`: passed
- `git diff --check`: passed

### Files Changed

- `.github/workflows/ci.yml`
- `README.md`
- `docs/SETUP.md`
- `scripts/ci_local_integration.py`
- `scripts/local_ollama_fixture.py`
- `tests/run_all.py`
- `tests/test_ci_workflow.py`
- `tests/test_docs_setup.py`
- `tests/test_local_integration_runner.py`
- `docs/reports/AUDIT_REPORT_122.md`
