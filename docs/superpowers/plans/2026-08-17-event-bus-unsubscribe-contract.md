# EventBus Unsubscribe Contract Implementation Plan

> **For agentic workers:** Execute inline in this session. Do not dispatch
> subagents, stage, or commit because the shared worktree contains overlapping
> user changes.

**Goal:** Make EventBus unsubscribe type-safe and truthfully report removal.

**Architecture:** Reject non-plain-integer IDs before locking; under the
existing lock, retain nonmatching records and track whether any record changed.

**Tech Stack:** Python 3.10+, `threading.Lock`, `unittest`, `pytest`.

## Global Constraints

- Preserve no-error behavior for missing IDs.
- Do not change ID allocation or callback semantics.
- Use TDD and observe the contract regression fail first.
- Do not stage or commit the mixed worktree.

---

### Task 1: Prove unsubscribe contract defects

**Files:**
- Modify: `tests/test_event_bus_extended.py`
- Modify: `tests/test_event_bus.py`

- [x] Add exact-type, found, repeated, and unknown-ID regression.
- [x] Update the legacy pytest expectation to the documented contract.
- [x] Run the focused regression and confirm expected failure.

### Task 2: Implement truthful removal

**Files:**
- Modify: `src/core/kernel/event_bus.py`

- [x] Reject non-plain-integer IDs without mutation.
- [x] Track and return actual removal under the lock.
- [x] Run EventBus, affected Plugin/Broker/HTTP, compileall, and Ruff checks.

### Task 3: Delivery evidence

**Files:**
- Modify: `AGENTS.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/reports/PROJECT_ANALYSIS.md`
- Modify: `docs/reports/README.md`
- Create: `docs/reports/AUDIT_REPORT_164.md`
- Remove: `docs/reports/AUDIT_REPORT_154.md`

- [x] Confirm the registered EventBus boundary class contributes the regression.
- [x] Self-review exact ID semantics, lock scope, callers, and diff.
- [x] Run all Python, frontend, integration, and repository consistency gates.
- [x] Update Iteration 164 ledgers and roll the report window to 155-164.
