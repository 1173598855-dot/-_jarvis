# Token Usage State Ownership Implementation Plan

> **For agentic workers:** Execute inline in this session. Do not dispatch
> subagents, stage, or commit because the shared worktree contains overlapping
> user changes.

**Goal:** Make shared Ollama token telemetry atomic and prevent callers from
rewriting service-owned session totals.

**Architecture:** One lock owns totals, latest usage, and a 60-entry deque.
Writers update one coherent state under the lock; readers return independent
value snapshots.

**Tech Stack:** Python 3.10+, `threading.Lock`, `collections.deque`, `unittest`.

## Global Constraints

- Keep HTTP token-usage fields and scalar sample dictionaries unchanged.
- Preserve negative-count clamping and compatible Ollama response parsing.
- Do not serialize network requests through the telemetry lock.
- Use TDD and observe ownership/concurrency regressions fail first.
- Do not stage or commit the mixed worktree.

---

### Task 1: Prove state ownership and concurrency defects

**Files:**
- Modify: `tests/test_ollama_manager.py`

- [x] Add a getter mutation regression.
- [x] Add deterministic simultaneous record updates with a yielding counter.
- [x] Add a 65-sample newest-60 FIFO regression.
- [x] Run `TestTokenUsage` and confirm expected failures.

### Task 2: Implement atomic token telemetry

**Files:**
- Modify: `src/core/kernel/ollama_manager.py`

- [x] Add the sample limit constant, deque, and token state lock.
- [x] Update totals/latest/samples atomically under the lock.
- [x] Return independent getter and complete HTTP snapshots under the lock.
- [x] Run focused manager, chat, role-usage, compileall, and Ruff checks.

### Task 3: Canonical coverage and delivery evidence

**Files:**
- Modify: `tests/run_all.py`
- Modify: `tests/test_run_all_coverage.py`
- Modify: `AGENTS.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/reports/PROJECT_ANALYSIS.md`
- Modify: `docs/reports/README.md`
- Create: `docs/reports/AUDIT_REPORT_160.md`
- Remove: `docs/reports/AUDIT_REPORT_150.md`

- [x] Register `TestTokenUsage` exactly once in the aggregate suite.
- [x] Self-review lock scope, update consistency, snapshots, FIFO, and diff.
- [x] Run all Python, frontend, integration, and repository consistency gates.
- [x] Update Iteration 160 ledgers and roll the report window to 151-160.
