# Aggregate Performance Temporary Ownership Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the aggregate MemoryStore performance test own and automatically remove its temporary files.

**Architecture:** A behavioral regression invokes the real benchmark from an isolated working directory and detects the old fixed-path leak. The benchmark then uses one `.test-perf-` `TemporaryDirectory` around all real store operations and its timing assertion.

**Tech Stack:** Python 3.10+, unittest, tempfile, pathlib.

## Global Constraints

- Preserve the ten real MemoryStore writes and 500 ms assertion.
- Keep runtime source and MemoryStore unchanged.
- Restore any temporary working-directory change in `finally`.
- Do not stage, commit, reset, clean, or revert the mixed worktree.

---

### Task 1: Behavioral Leak Regression

**Files:**
- Modify: `tests/test_run_all_coverage.py`

**Interfaces:**
- Consumes: `run_all.TestPerformance.test_store_speed`
- Produces: a regression proving the legacy `.test-perf` path is absent after execution

- [x] **Step 1: Add the isolated-working-directory regression**

Run the real unittest case inside an outer `TemporaryDirectory`, restore the
original cwd in `finally`, require a successful result, and assert
`Path(temporary) / ".test-perf"` does not exist.

- [x] **Step 2: Verify RED**

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_run_all_coverage.TestRunAllCoverage.test_store_performance_does_not_leave_repository_scratch -v
```

Expected: failure because the current benchmark creates `.test-perf`.

### Task 2: Owned Benchmark Directory

**Files:**
- Modify: `tests/run_all.py`

**Interfaces:**
- Consumes: `tempfile.TemporaryDirectory(prefix=".test-perf-")`
- Produces: unchanged benchmark assertions with automatic directory cleanup

- [x] **Step 1: Replace the fixed path with context ownership**

Import `tempfile`, create the MemoryStore inside the context, keep all ten
writes and the timing assertion inside it, and remove inline `shutil` cleanup.

- [x] **Step 2: Verify GREEN**

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_run_all_coverage.TestRunAllCoverage.test_store_performance_does_not_leave_repository_scratch -v
Set-Location tests
..\venv\Scripts\python.exe -m unittest run_all.TestPerformance -v
Set-Location ..
```

Expected: regression and both performance cases pass; no `.test-perf` remains.

### Task 3: Review, Full Evidence, And Ledger

**Files:**
- Modify: `AGENTS.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/reports/PROJECT_ANALYSIS.md`
- Modify: `docs/reports/README.md`
- Create: `docs/reports/AUDIT_REPORT_151.md`
- Delete: `docs/reports/AUDIT_REPORT_141.md`

**Interfaces:**
- Consumes: final code, regression, and fresh verification totals
- Produces: Iteration 151 evidence and rolling report window 142-151

- [x] **Step 1: Self-review cleanup semantics and scope**

Confirm context ownership surrounds the assertion, cwd restoration is
exception-safe, no broad path deletion remains, and runtime source is untouched.

- [x] **Step 2: Run complete project gates**

Run aggregate/discovery, compileall, Ruff, Vitest, Playwright, typecheck,
build, deterministic local integration, and `git diff --check`.

- [x] **Step 3: Update Iteration 151 evidence and rolling window**

Record fresh totals, add `AUDIT_REPORT_151.md`, remove only report 141, update
current-state documents, and mark every plan step complete.

- [x] **Step 4: Run final guards**

Run iteration-ledger/docs guards, Ruff, `git diff --check`, exact scratch-path
checks, and `git status --short`.
