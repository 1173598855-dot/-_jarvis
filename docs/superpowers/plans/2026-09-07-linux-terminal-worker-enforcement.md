# Linux Terminal Worker Enforcement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add mutation-checked Linux kernel-enforcement evidence for the real fixed `TerminalWorker` request and cleanup chain without changing its production protocol.

**Architecture:** Stage the trusted source tree, run a real unprivileged driver through production `TerminalWorker.execute()`, and narrowly substitute its child command with a shim that invokes the same production `_worker_main()` while probing access after isolation. Reuse the existing bounded output and nested process-tree cleanup helpers, then enable the three evidence modes only in the Linux sandbox job.

**Tech Stack:** Python 3.11 standard library, Linux namespaces, Landlock, `unittest`, GitHub Actions.

## Global Constraints

- Do not modify production source or expose a probe through the Terminal request contract.
- Do not add dependencies, direct-spawn fallbacks or isolation-disable behavior outside the test shim.
- Normal non-Linux and non-opt-in runs must report exactly three honest skips.
- Preserve unrelated dirty-worktree changes and use `.test-*` for repository scratch.
- Bound each driver stream to 8 KiB, the driver to 20 seconds and cleanup confirmation to the existing fixed timeout.

---

### Task 1: Lock Aggregate And CI Routing

**Files:**
- Modify: `tests/test_run_all_coverage.py`
- Modify: `tests/test_ci_workflow.py`

**Interfaces:**
- Consumes: `run_all.AGGREGATE_TEST_CASES` and the `linux-sandbox` workflow block.
- Produces: failing contracts for `TestLinuxTerminalWorkerEnforcement`, its test module and `JARVIS_RUN_LINUX_TERMINAL_WORKER_ENFORCEMENT=1`.

- [x] **Step 1: Add the aggregate coverage assertion**

Add a guard requiring the pair
`("test_linux_terminal_worker_enforcement", "TestLinuxTerminalWorkerEnforcement")`
exactly once in `AGGREGATE_TEST_CASES`.

- [x] **Step 2: Extend the Linux workflow assertion**

Require `tests.test_linux_terminal_worker_enforcement` in the existing unittest
command and the exact opt-in environment assignment below it.

- [x] **Step 3: Run RED**

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_run_all_coverage.TestRunAllCoverage.test_aggregate_runner_includes_linux_terminal_worker_enforcement_guard_once tests.test_ci_workflow.TestCiWorkflow.test_linux_sandbox_job_runs_the_opt_in_real_enforcement_probe -v
```

Expected: both tests fail because the aggregate and workflow do not yet contain
the Terminal production-chain probe.

### Task 2: Add The Opt-In Production-Chain Probe

**Files:**
- Create: `tests/test_linux_terminal_worker_enforcement.py`

**Interfaces:**
- Consumes: `TerminalWorker`, `TerminalCommand`, `stage_worker_tree()`, and the existing `_collect_bounded_probe_output()` / `_terminate_linux_probe_tree()` helpers.
- Produces: `TestLinuxTerminalWorkerEnforcement` with full, filesystem-disabled and network-disabled evidence modes gated by `JARVIS_RUN_LINUX_TERMINAL_WORKER_ENFORCEMENT=1`.

- [x] **Step 1: Build the bounded outer fixture**

Stage `src/`, create the outside and source-marker files, hold a real loopback
listener, run the driver under UID/GID 12345 when root, and require one bounded
UTF-8 JSON document. On timeout, overflow or parse failure, reclaim recorded
Worker groups before the driver group.

- [x] **Step 2: Build the production parent driver**

Import `TerminalWorker` from the staged tree, verify baseline access, wrap only
the exact Terminal child `Popen` command, call `execute()` with a fixed `echo`
request, decode probe JSON from `TerminalResult.stdout`, and record PID,
correlation, exit and Worker-root cleanup evidence.

- [x] **Step 3: Build the child shim**

Import the same production module, optionally replace one isolation function
with a no-op for mutation evidence, replace only
`_run_read_only_operation()`, and call `_worker_main()`. The operation must
attempt outside read/write, source-marker read/write, loopback connect and one
Worker-root write before returning sorted JSON.

- [x] **Step 4: Verify real GREEN and mutation sensitivity**

```bash
JARVIS_RUN_LINUX_TERMINAL_WORKER_ENFORCEMENT=1 python3 -m unittest tests.test_linux_terminal_worker_enforcement -v
```

Expected on Ubuntu 24.04 WSL2: three passed. The full mode reports filesystem
and network denial; each mutation mode exposes only the disabled boundary.

### Task 3: Wire The Probe And Close Iteration 248

**Files:**
- Modify: `tests/run_all.py`
- Modify: `.github/workflows/ci.yml`
- Modify: `AGENTS.md`
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/DEVELOPMENT_GUIDE.md`
- Modify: `docs/reports/PROJECT_ANALYSIS.md`
- Modify: `docs/reports/README.md`
- Create: `docs/reports/AUDIT_REPORT_248.md`

**Interfaces:**
- Consumes: measured Windows, WSL2, aggregate, discovery and frontend verification.
- Produces: aggregate/CI execution plus exact current-state Iteration 248 evidence.

- [x] **Step 1: Wire GREEN**

Import and append `TestLinuxTerminalWorkerEnforcement` in `tests/run_all.py`.
Add the module and opt-in variable to the existing `linux-sandbox` job, then
rerun the two RED contracts and the ordinary probe module skip path.

- [x] **Step 2: Run focused verification**

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_linux_terminal_worker_enforcement tests.test_terminal_worker tests.test_worker_network_isolation tests.test_worker_filesystem_isolation tests.test_run_all_coverage tests.test_ci_workflow -v
.\venv\Scripts\python.exe -m ruff check src tests scripts
.\venv\Scripts\python.exe -m compileall -q src tests scripts
```

- [x] **Step 3: Run complete verification**

Run the canonical aggregate and bounded discovery suites with `.test-*` JSON
reports, then Vitest, Playwright, typecheck and build.

- [ ] **Step 4: Self-review and record evidence**

Review command substitution strictness, UID/GID baseline, exact mutation
outcomes, output/process budgets, cleanup ownership, platform skips and scoped
diff. Record only observed counts, roll report navigation to Iterations 239-248
without deleting unrelated worktree files, run documentation contracts and
finish with `git diff --check` plus `git status --short`.
