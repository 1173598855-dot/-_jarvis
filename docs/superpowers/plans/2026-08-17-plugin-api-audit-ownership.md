# Plugin API Audit Ownership Implementation Plan

> **For agentic workers:** Execute inline in this session. Do not dispatch
> subagents, stage, or commit because the shared worktree contains overlapping
> user changes.

**Goal:** Bound Plugin API access history and prevent plugin-facing snapshots
from rewriting Worker-owned audit evidence.

**Architecture:** `XiaoYiPluginAPI` owns a fixed-capacity deque and audit lock.
Each ownership boundary receives its own scalar dictionary copy, and the
external sink runs outside the lock.

**Tech Stack:** Python 3.10+, `collections.deque`, `threading.Lock`, `unittest`.

## Global Constraints

- Keep the existing audit schema and 200-character argument representation.
- Preserve permission, Broker, sink exception, lifecycle, and wire behavior.
- Keep the external audit sink outside the internal lock.
- Use TDD and observe every new regression fail before production edits.
- Do not stage or commit the mixed worktree.

---

### Task 1: Prove Plugin API retention and ownership defects

**Files:**
- Modify: `tests/test_plugin_sdk.py`

**Interfaces:**
- Consumes: `XiaoYiPluginAPI.log_access()` and `get_audit_log()`.
- Produces: four regressions for capacity, getter ownership, sink ownership,
  and limit validation.

- [x] Add a 1005-entry test expecting exactly 1000 retained records in oldest
  to newest order from `call-5` through `call-1004`.
- [x] Add a test proving mutation of a getter snapshot cannot change a later
  snapshot.
- [x] Add a mutating audit sink test proving sink changes cannot affect local
  history and local snapshot changes cannot affect sink evidence.
- [x] Add exact non-negative integer limit tests, including zero, negative,
  boolean, float, and string values.
- [x] Run the Plugin API test class and confirm capacity, alias, and validation
  assertions fail for the expected reasons.

### Task 2: Implement bounded, isolated audit ownership

**Files:**
- Modify: `src/core/kernel/plugin_api.py`

**Interfaces:**
- Produces: `PLUGIN_API_AUDIT_LIMIT = 1000`, lock-protected deque storage,
  copied getter records, and copied lock-free sink delivery.

- [x] Add the capacity constant, deque storage, and a dedicated audit lock.
- [x] Append under the lock, then call the sink outside the lock with
  `entry.copy()` while preserving exception propagation.
- [x] Validate getter limits and return copied selected entries under the lock.
- [x] Re-run Plugin API tests and all Plugin-focused suites with
  `ResourceWarning` enabled.
- [x] Run focused compileall and Ruff checks.

### Task 3: Canonical coverage, review, and delivery evidence

**Files:**
- Modify: `tests/run_all.py`
- Modify: `tests/test_run_all_coverage.py`
- Modify: `AGENTS.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/reports/PROJECT_ANALYSIS.md`
- Modify: `docs/reports/README.md`
- Create: `docs/reports/AUDIT_REPORT_158.md`
- Remove: `docs/reports/AUDIT_REPORT_148.md`

**Interfaces:**
- Consumes: TDD and full-gate results.
- Produces: canonical Plugin API coverage and Iteration 158 evidence.

- [x] RED/GREEN a runner guard, then register the existing
  `TestXiaoYiPluginAPI` class exactly once in the aggregate suite.
- [x] Self-review capacity, order, lock scope, ownership copies, invalid
  limits, sink errors, unchanged API behavior, and diff scope.
- [x] Measure aggregate and discovery totals, then update Iteration 158 and
  roll the report window from 148-157 to 149-158.
- [x] Run compileall, Ruff, Vitest, Playwright, typecheck, build,
  required-services integration, and `git diff --check`.
- [x] Run final ledger, report-count, scratch-directory, listener, plan, and
  Git status guards.
