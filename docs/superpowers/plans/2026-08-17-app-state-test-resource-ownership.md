# AppState Test Resource Ownership Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop legacy AppState tests from relying on implicit TerminalWorker temporary-directory cleanup.

**Architecture:** A subprocess regression observes complete module stderr with ResourceWarning enabled. Each legacy TestAppState class then owns one real state per test and registers the existing idempotent `AppState.shutdown()` through unittest cleanup.

**Tech Stack:** Python 3.10+, unittest, subprocess, ResourceWarning.

## Global Constraints

- Keep production source and default AppState composition unchanged.
- Exercise full `AppState.shutdown()`, not only `TerminalWorker.close()`.
- Keep warning visibility enabled; do not add filters or suppressions.
- Preserve existing test assertions and real default resources.
- Do not stage, commit, reset, clean, or revert the mixed worktree.

---

### Task 1: Warning-Enabled Subprocess Regression

**Files:**
- Modify: `tests/test_run_all_coverage.py`

**Interfaces:**
- Consumes: `sys.executable`, unittest module names, process stderr
- Produces: one regression proving both legacy modules own TerminalWorker cleanup

- [x] **Step 1: Add the subprocess guard**

Import `subprocess`. For
`tests.test_main_extended.TestAppStateExtended` and
`tests.test_main_fastapi_extended.TestAppState`, run this exact child shape with
a 60-second timeout, repository cwd, captured UTF-8 text, and replacement decoding:

```python
[
    sys.executable,
    "-W",
    "always::ResourceWarning",
    "-m",
    "unittest",
    target,
]
```

Require return code zero and reject both `jarvis-terminal-worker-` and
`Implicitly cleaning up` in stderr.

- [x] **Step 2: Verify RED**

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_run_all_coverage.TestRunAllCoverage.test_legacy_app_state_tests_close_terminal_worker_directories -v
```

Expected: failure for the first legacy class because its stderr contains an
implicit `jarvis-terminal-worker-*` TemporaryDirectory cleanup warning.

### Task 2: Explicit Legacy State Ownership

**Files:**
- Modify: `tests/test_main_extended.py`
- Modify: `tests/test_main_fastapi_extended.py`

**Interfaces:**
- Consumes: `AppState.shutdown() -> None`, unittest `addCleanup`
- Produces: deterministic full cleanup for every locally constructed default state

- [x] **Step 1: Own main HTTP AppState resources**

Add `TestAppStateExtended.setUp`, assign `self.state = AppState()`, and register
`self.addCleanup(self.state.shutdown)`. Change all nine tests to use
`self.state`; remove the terminal-only `try/finally`.

- [x] **Step 2: Own FastAPI AppState resources**

Add an owned `.test-fastapi-app-state-` `TemporaryDirectory` to
`TestAppState.setUp` and register its cleanup first. Construct `self.state`
with that memory directory and register `self.state.shutdown` second so LIFO
cleanup shuts the state down before directory removal. Change all three tests
to use `self.state` and remove terminal-only cleanup.

- [x] **Step 3: Verify GREEN**

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_run_all_coverage.TestRunAllCoverage.test_legacy_app_state_tests_close_terminal_worker_directories -v
.\venv\Scripts\python.exe -W always::ResourceWarning -m unittest tests.test_main_extended tests.test_main_fastapi_extended -v
```

Expected: all tests pass and output contains no implicit TerminalWorker
TemporaryDirectory warning.

### Task 3: Review, Full Evidence, And Ledger

**Files:**
- Modify: `AGENTS.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/reports/PROJECT_ANALYSIS.md`
- Modify: `docs/reports/README.md`
- Create: `docs/reports/AUDIT_REPORT_153.md`
- Delete: `docs/reports/AUDIT_REPORT_143.md`

**Interfaces:**
- Consumes: final tests and fresh verification totals
- Produces: Iteration 153 evidence and rolling report window 144-153

- [x] **Step 1: Self-review resource ownership and scope**

Confirm every local legacy state registers full shutdown before assertions,
the subprocess guard covers both modules, no warning filter exists, and no
production file changed.

- [x] **Step 2: Run complete project gates**

Run aggregate/discovery, compileall, Ruff, Vitest, Playwright, typecheck,
production build, deterministic required-services integration, and
`git diff --check`.

- [x] **Step 3: Update Iteration 153 evidence and rolling window**

Record fresh totals, add `AUDIT_REPORT_153.md`, remove only report 143, update
current-state documents, and mark every plan checkbox complete.

- [x] **Step 4: Run final guards**

Re-run the warning subprocess regression, iteration ledger, Ruff, full diff
whitespace, report count, `.test-*` root paths, test listeners, and Git status.
