# Bounded Orchestrator History Implementation Plan

> **For agentic workers:** Execute inline in this session. Do not dispatch
> subagents, stage, or commit because the shared worktree contains overlapping
> user changes.

**Goal:** Bound orchestrator task history and prevent query or caller mutation
from rewriting retained result evidence.

**Architecture:** Store copied `AgentResult` values in a fixed-capacity deque.
Collect newest matching records under the history lock, then return independent
copies with an exact non-negative integer limit contract.

**Tech Stack:** Python 3.10+, `collections.deque`, `copy.deepcopy`, `unittest`.

## Global Constraints

- Preserve dispatch return types, retry decisions, stats, and API output.
- Retain newest-first `collect()` order.
- Keep all history reads and writes under the existing history lock.
- Use TDD and observe each regression fail before production edits.
- Do not stage or commit the mixed worktree.

---

### Task 1: Prove retention, query, and ownership defects

**Files:**
- Modify: `tests/test_orchestrator_extended_v2.py`

- [x] Add a 1005-entry regression expecting the newest 1000 records.
- [x] Add exact non-negative integer limit tests, including zero.
- [x] Add a filter-before-limit regression.
- [x] Add record-input and returned-snapshot ownership regressions.
- [x] Run the focused class and confirm expected failures.

### Task 2: Implement bounded independent history

**Files:**
- Modify: `src/core/brain/orchestrator.py`

- [x] Add the history capacity constant and deque storage.
- [x] Copy records at the write and read ownership boundaries.
- [x] Validate limits and filter before taking the newest result window.
- [x] Re-run focused orchestrator tests, compileall, and Ruff.

### Task 3: Canonical coverage and delivery evidence

**Files:**
- Modify: `tests/run_all.py`
- Modify: `tests/test_run_all_coverage.py`
- Modify: `AGENTS.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/reports/PROJECT_ANALYSIS.md`
- Modify: `docs/reports/README.md`
- Create: `docs/reports/AUDIT_REPORT_159.md`
- Remove: `docs/reports/AUDIT_REPORT_149.md`

- [x] Register the new regression class exactly once in the aggregate suite.
- [x] Self-review capacity, order, lock scope, copies, filters, and diff scope.
- [x] Run aggregate, discovery, compileall, Ruff, frontend, integration, and
  repository consistency gates.
- [x] Update Iteration 159 ledgers and roll the report window to 150-159.
