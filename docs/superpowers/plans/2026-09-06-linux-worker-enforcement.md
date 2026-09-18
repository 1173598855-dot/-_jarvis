# Linux Worker Enforcement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Linux Worker namespace/Landlock isolation work for unprivileged users on modern kernels and prove its kernel behavior with a real platform-gated test.

**Architecture:** Preserve the privileged direct network-namespace path, add a fail-closed user-namespace fallback only for `EPERM`, and cap requested Landlock rights to the newest ABI understood by this code while recording the real kernel ABI. A dedicated real-child probe composes the production primitives in production order and is explicitly enabled in WSL2 and Ubuntu CI.

**Tech Stack:** Python 3.10+, standard-library `ctypes`, Linux namespaces, Landlock, `unittest`, GitHub Actions.

## Global Constraints

- No new dependency.
- No direct-spawn or isolation-disable fallback.
- No Plugin/Terminal protocol or Broker contract change.
- Non-Linux and ordinary aggregate runs must skip the real enforcement probe honestly.
- Preserve all unrelated working-tree changes.

---

### Task 1: Landlock forward compatibility

**Files:**
- Modify: `tests/test_worker_filesystem_isolation.py`
- Modify: `src/core/kernel/worker_filesystem_isolation.py`

**Interfaces:**
- Consumes: `_handled_access_for_abi(abi: int) -> int`
- Produces: ABI values `>=3` select `LANDLOCK_ACCESS_FS_ABI_3` without hiding the actual queried ABI from the caller.

- [x] Add a unit test whose fake API reports ABI 7 and expects successful restriction using the ABI 3 access mask plus evidence `landlock_abi_7`.
- [x] Run the test and confirm it fails with `unsupported Worker filesystem isolation ABI: 7`.
- [x] Replace the `abi > 3` rejection with monotonic ABI selection: `abi >= 3`, `abi >= 2`, otherwise ABI 1.
- [x] Run the filesystem isolation module and confirm all cases pass.

### Task 2: Unprivileged network namespace fallback

**Files:**
- Modify: `tests/test_worker_network_isolation.py`
- Modify: `src/core/kernel/worker_network_isolation.py`

**Interfaces:**
- Consumes: `isolate_worker_network(*, ctypes_module=None, platform_name=None) -> tuple[str, ...]`
- Produces: `CLONE_NEWUSER`, `CLONE_NEWNET`, `_map_current_identity(uid, gid)`, and an EPERM-only two-syscall path that retains the existing return contract.

- [x] Add unit tests proving direct success performs no identity mapping, `EPERM` retries with combined user/network flags and maps the captured identity, non-`EPERM` errors do not retry, and map failures fail closed.
- [x] Run those tests and confirm the missing fallback behavior fails.
- [x] Add fixed-size `/proc/self` writers that reject partial writes and close errors, plus the EPERM-only namespace fallback.
- [x] Run the network isolation and Worker entrypoint/terminal integration modules.

### Task 3: Real Linux enforcement probe and CI route

**Files:**
- Create: `tests/test_linux_worker_isolation_enforcement.py`
- Modify: `.github/workflows/ci.yml`
- Modify: `tests/test_ci_workflow.py`
- Modify: `tests/run_all.py` only if the aggregate suite requires explicit inclusion.

**Interfaces:**
- Consumes: production `isolate_worker_network()` and `isolate_worker_filesystem(..., root_writable=True)`.
- Produces: an opt-in Linux test enabled by `JARVIS_RUN_LINUX_ISOLATION_ENFORCEMENT=1` and a `linux-sandbox` CI job.

- [x] Add the real child test with an active parent listener and exact read/write/network assertions.
- [x] Run it before the fixes (or against a reverted fix) and confirm the ABI 7 failure is detected.
- [x] Enable it locally in Ubuntu 24.04 WSL2 and confirm the unprivileged child passes.
- [x] Add an Ubuntu CI job and static workflow assertions that explicitly enable the probe.
- [x] Run focused probe and workflow tests; re-run aggregate coverage after Iteration 245 metrics replace the expected Iteration 244 ledger counts.

### Task 4: Self-review, documentation, and full verification

**Files:**
- Modify: `AGENTS.md`
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/DEVELOPMENT_GUIDE.md`
- Modify: `docs/reports/PROJECT_ANALYSIS.md`
- Modify: `docs/reports/README.md`
- Create: `docs/reports/AUDIT_REPORT_245.md`

**Interfaces:**
- Consumes: fresh command output from focused and full verification.
- Produces: exact Iteration 245 evidence that distinguishes Windows skips, WSL2 enforcement, and the Ubuntu CI evidence path.

- [x] Review the scoped diff for namespace ordering, partial-write/cleanup errors, ABI masks, platform skips, and unrelated changes; fix high-confidence issues.
- [x] Run Ruff and compileall.
- [x] Run `tests/run_all.py --timeout 1800` and `scripts/discover_tests.py --timeout 1800` with JSON reports.
- [x] Run the frontend unit, typecheck, build, and browser suites because shared project evidence documents are updated.
- [x] Update all current-state documents and write `AUDIT_REPORT_245.md` using only fresh observed counts.
- [x] Re-run documentation contract tests and `git diff --check` on Iteration 245 paths.
