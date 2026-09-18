# EventBus Once-Subscription Claim Implementation Plan

> **For agentic workers:** Execute inline in this session. Do not dispatch
> subagents, stage, or commit because the shared worktree contains overlapping
> user changes.

**Goal:** Guarantee at-most-once EventBus callback execution under concurrent
and reentrant emits.

**Architecture:** Under the existing subscriber lock, collect matching
callbacks and remove once records before releasing the lock. Invoke callbacks
from that immutable selection outside the lock.

**Tech Stack:** Python 3.10+, `threading.Lock`, `unittest`.

## Global Constraints

- Never execute user callbacks while holding the EventBus lock.
- Preserve normal and wildcard subscriber behavior and error isolation.
- Preserve Event history and identity semantics.
- Use TDD and observe concurrent and reentrant failures first.
- Do not stage or commit the mixed worktree.

---

### Task 1: Prove delayed once-removal defects

**Files:**
- Modify: `tests/test_event_bus_extended.py`

- [x] Add synchronized concurrent emit regression.
- [x] Add reentrant emit regression.
- [x] Run both tests and confirm expected failures.

### Task 2: Claim once subscriptions before callbacks

**Files:**
- Modify: `src/core/kernel/event_bus.py`

- [x] Select and remove once subscriptions under the existing lock.
- [x] Keep callback execution and exception handling outside the lock.
- [x] Run EventBus, Plugin/Broker/HTTP, compileall, and Ruff checks.

### Task 3: Delivery evidence

**Files:**
- Modify: `AGENTS.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/reports/PROJECT_ANALYSIS.md`
- Modify: `docs/reports/README.md`
- Create: `docs/reports/AUDIT_REPORT_163.md`
- Remove: `docs/reports/AUDIT_REPORT_153.md`

- [x] Confirm the already-registered EventBus boundary class contributes the new tests.
- [x] Self-review lock scope, wildcard selection, reentrancy, and diff.
- [x] Run all Python, frontend, integration, and repository consistency gates.
- [x] Update Iteration 163 ledgers and roll the report window to 154-163.
