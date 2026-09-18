# Ruff Zero-Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the repository's existing CI Ruff command exit zero without changing runtime behavior or hiding findings globally.

**Architecture:** Use Ruff 0.16.2 itself for its 98 safe mechanical fixes, then resolve the seven unsafe-fix candidates explicitly and annotate only four path-bootstrap modules for E402. Review the resulting diff before running the complete project verification and Iteration 149 evidence update.

**Tech Stack:** Python 3.10+ source, Ruff 0.16.2, unittest, existing frontend and integration gates.

## Global Constraints

- Do not run Ruff with `--unsafe-fixes`.
- Do not add project-wide or directory-wide rule ignores.
- Preserve public imports, API schemas, dependencies, runtime behavior, and all mixed-worktree changes.
- Do not stage, commit, reset, clean, or revert files.
- The exit gate is the unchanged command `python -m ruff check src tests scripts`.

---

### Task 1: Apply And Review Ruff Safe Fixes

**Files:**
- Modify mechanically: the current I001/F401/F541/F811 files under `src/`, `tests/`, and `scripts/` reported by Ruff
- Inspect: every file listed by `git diff --name-only` before and after the command

**Interfaces:**
- Consumes: the recorded 153-finding baseline and Ruff's safe-fix metadata
- Produces: import ordering, unused-import cleanup, redundant f-string cleanup, and unused redefinition cleanup only

- [x] **Step 1: Reconfirm the RED baseline**

```powershell
.\venv\Scripts\python.exe -m ruff check src tests scripts --statistics
```

Expected: exit 1 with 153 findings and 98 fixable.

- [x] **Step 2: Apply only safe fixes**

```powershell
.\venv\Scripts\python.exe -m ruff check src tests scripts --fix
```

Expected: 97 non-overlapping safe fixes applied; E402, E731, F601, and F841
remain. Ruff counts the removed duplicate import under overlapping F401/F811
diagnostics in the original 98-fixable summary.

- [x] **Step 3: Inspect the mechanical diff**

```powershell
git diff --stat
git diff -- src tests scripts
```

Confirm that changes are limited to import ordering/removal, redundant `f`
prefix removal, and the unused redefinition. Restore nothing through Git;
apply a scoped patch only if Ruff removed an intentional public import.

- [x] **Step 4: Recount remaining findings**

```powershell
.\venv\Scripts\python.exe -m ruff check src tests scripts --statistics
```

Expected: 53 findings remain: 46 E402, 5 F841, 1 E731, and 1 F601. Import
sorting coalesces two previously separate E402 diagnostics.

### Task 2: Resolve The Seven Judgment-Requiring Findings

**Files:**
- Modify: `scripts/ci_local_integration.py`
- Modify: `scripts/ruff_check.py`
- Modify: `src/core/kernel/terminal_executor.py`
- Modify: `tests/test_role_tool_loop.py`

**Interfaces:**
- Consumes: Ruff locations for F841, F601, and E731
- Produces: behavior-preserving explicit source with no unsafe auto-fix

- [x] **Step 1: Preserve process behavior while removing four unused assignments**

In `scripts/ci_local_integration.py`, change the temporary-directory context to
omit its unused `as temp_dir` target, remove `temp_path = Path(temp_dir)`, then
change `fixture = start(...)`, `core = start(...)`, and `express = start(...)`
to direct `start(...)` calls. Keep process-list registration, arguments, health
waits, lifetime, and `finally` cleanup unchanged.

- [x] **Step 2: Remove the unused timer assignment**

In `src/core/kernel/terminal_executor.py`, remove only
`start_time = time.time()` at the reported F841 location. Do not alter
timeout calculation or result timing elsewhere.

- [x] **Step 3: Replace the assigned lambda with a local function**

In `tests/test_role_tool_loop.py`, replace the reported
`clock = lambda: next(ticks)` with:

```python
def clock():
    return next(ticks)
```

Keep the iterator and all elapsed-budget assertions unchanged.

- [x] **Step 4: Resolve the repeated dictionary key deliberately**

Inspect `scripts/ruff_check.py` around the two literal `"UP"` entries. Remove
the earlier entry only after confirming the later value is the mapping Python
currently retains at runtime.

- [x] **Step 5: Verify only E402 remains**

```powershell
.\venv\Scripts\python.exe -m ruff check src tests scripts --statistics
```

Expected: exactly 48 E402 findings.

### Task 3: Document Four Intentional Import Bootstrap Boundaries

**Files:**
- Modify: `src/runtime/plugin_worker.py`
- Modify: `tests/run_all.py`
- Modify: `tests/test_plugin_installation.py`
- Modify: `tests/test_run_all_coverage.py`

**Interfaces:**
- Consumes: required `sys.path` setup before project-local imports
- Produces: four narrowly documented file-level E402 suppressions

- [x] **Step 1: Confirm each import follows required bootstrap code**

Read the top of all four files and verify the reported imports follow either a
repository/test path insertion or a dynamic aggregate-runner load that must run
first.

- [x] **Step 2: Add the scoped directives**

Add `# ruff: noqa: E402` near the module header in each file, next to a short
comment explaining that standalone or aggregate bootstrap must precede local
imports. Do not suppress another rule.

- [x] **Step 3: Require the Ruff gate to become GREEN**

```powershell
.\venv\Scripts\python.exe -m ruff check src tests scripts
```

Expected: exit 0 and `All checks passed!`.

- [x] **Step 4: Run focused bootstrap and script checks**

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_plugin_installation tests.test_run_all_coverage tests.test_role_tool_loop -v
.\venv\Scripts\python.exe scripts\ci_local_integration.py --require-services
```

Expected: selected tests and the deterministic integration profile pass.

### Task 4: Full Regression, Self-Review, And Iteration 149 Evidence

**Files:**
- Modify: `AGENTS.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/DEVELOPMENT_GUIDE.md`
- Modify: `docs/reports/PROJECT_ANALYSIS.md`
- Modify: `docs/reports/README.md`
- Create: `docs/reports/AUDIT_REPORT_149.md`
- Delete: `docs/reports/AUDIT_REPORT_139.md`
- Modify: `docs/superpowers/plans/2026-08-17-ruff-zero-baseline.md`

**Interfaces:**
- Consumes: fresh zero-Ruff and regression results
- Produces: Iteration 149 current state, rolling report window 140-149, and reproducible verification evidence

- [x] **Step 1: Perform an exact diff self-review**

Review reuse, quality, efficiency, and clarity. Confirm that no import removal
changes an `__all__`, public adapter surface, monkeypatch target, optional
platform branch, or process bootstrap. Confirm the repeated-key removal
preserves the value Python used before the edit.

- [x] **Step 2: Run the complete Python gates**

```powershell
.\venv\Scripts\python.exe tests\run_all.py
.\venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
.\venv\Scripts\python.exe -m compileall -q src tests scripts
.\venv\Scripts\python.exe -m ruff check src tests scripts
```

Expected: aggregate 641 total with 639 passed and 2 skipped; discovery 1584
total with 1582 passed and 2 skipped; compileall and Ruff exit zero.

- [x] **Step 3: Run frontend, browser, and integration gates**

```powershell
Set-Location frontend
npm test -- --run
$env:JARVIS_E2E_PORT = "5174"
try { npm run test:e2e } finally { Remove-Item Env:JARVIS_E2E_PORT -ErrorAction SilentlyContinue }
npm run typecheck
npm run build
Set-Location ..
.\venv\Scripts\python.exe scripts\ci_local_integration.py --require-services
git diff --check
```

Expected: Vitest 137, Playwright 7 passed and 1 conditional skip, typecheck,
build, integration, and whitespace checks pass.

- [x] **Step 4: Update the rolling evidence**

Record exact fresh totals, zero Ruff findings, affected file scope, and the
four E402 exceptions. Remove only `AUDIT_REPORT_139.md`, leaving exactly ten
reports from 140 through 149. Recalculate current source/test file and nonempty
line counts after mechanical cleanup.

- [x] **Step 5: Run final consistency guards**

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_iteration_ledger tests.test_readme tests.test_docs_setup tests.test_project_config -v
.\venv\Scripts\python.exe -m ruff check src tests scripts
git diff --check
git status --short
```

Expected: all documentation guards and Ruff pass, whitespace is clean, and no
unrelated worktree path was staged, committed, reset, cleaned, or reverted.
