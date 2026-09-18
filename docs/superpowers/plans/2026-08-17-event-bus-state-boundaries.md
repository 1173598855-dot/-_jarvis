# EventBus State Boundaries Implementation Plan

> **For agentic workers:** Execute inline in this session. Do not dispatch
> subagents, stage, or commit because the shared worktree contains overlapping
> user changes.

**Goal:** Make EventBus subscription IDs unique under concurrency and close
history limit edge cases.

**Architecture:** The existing bus lock owns ID reservation together with
subscriber append. Query limits are validated before taking a chronological
snapshot; Event values keep their current identity semantics.

**Tech Stack:** Python 3.10+, `threading.Lock`, `deque`, `unittest`.

## Global Constraints

- Preserve callback execution outside the lock and once-subscription behavior.
- Preserve Event identity used by Plugin Worker commit paths.
- Keep history filtering before the newest result limit.
- Use TDD and observe both regressions fail first.
- Do not stage or commit the mixed worktree.

---

### Task 1: Prove subscription and query defects

**Files:**
- Modify: `tests/test_event_bus_extended.py`

- [x] Add deterministic concurrent subscription ID regression.
- [x] Add exact non-negative limit and zero-result regression.
- [x] Run the focused class and confirm expected failures.

### Task 2: Implement state boundaries

**Files:**
- Modify: `src/core/kernel/event_bus.py`

- [x] Move ID reservation inside the existing subscriber lock section.
- [x] Validate exact non-negative history limits and handle zero explicitly.
- [x] Run all EventBus and affected Plugin tests, compileall, and Ruff.

### Task 3: Canonical coverage and delivery evidence

**Files:**
- Modify: `tests/run_all.py`
- Modify: `tests/test_run_all_coverage.py`
- Modify: `AGENTS.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/reports/PROJECT_ANALYSIS.md`
- Modify: `docs/reports/README.md`
- Create: `docs/reports/AUDIT_REPORT_162.md`
- Remove: `docs/reports/AUDIT_REPORT_152.md`

- [x] Register `TestEventBusStateBoundaries` exactly once in the aggregate suite.
- [x] Self-review lock scope, Event identity, query order, and diff.
- [x] Run all Python, frontend, integration, and repository consistency gates.
- [x] Update Iteration 162 ledgers and roll the report window to 153-162.
