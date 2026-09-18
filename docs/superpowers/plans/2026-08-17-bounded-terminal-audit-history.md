# Bounded Terminal Audit History Implementation Plan

> **For agentic workers:** Execute inline in this session. Do not dispatch
> subagents, stage, or commit because the shared worktree contains overlapping
> user changes.

**Goal:** Bound both terminal audit histories at 1000 immutable snapshot
entries without changing terminal execution or HTTP behavior.

**Architecture:** Export one terminal audit capacity constant from
`terminal_executor.py`. Each terminal implementation stores records in its own
fixed-capacity deque and serializes append, snapshot, and clear operations with
an audit-specific lock.

**Tech Stack:** Python 3.10+, `collections.deque`, `threading.Lock`, `unittest`.

## Global Constraints

- Preserve the existing terminal record schema and audited execution paths.
- Keep terminal lifecycle locks independent from audit snapshot operations.
- Do not change process, command, risk, response, or HTTP contracts.
- Use TDD and observe each new regression fail before production edits.
- Do not stage or commit the mixed worktree.

---

### Task 1: Prove bounded and isolated Worker history

**Files:**
- Modify: `tests/test_terminal_worker.py`
- Modify: `src/core/kernel/terminal_worker.py`
- Modify: `src/core/kernel/terminal_executor.py`

**Interfaces:**
- Consumes: `TerminalWorker.execute()`, `get_audit_log()`, and
  `clear_audit_log()`.
- Produces: a 1000-entry fixed-capacity Worker history returning copied
  dictionaries.

- [x] Add a test that creates 1005 policy-rejected Worker calls without child
  processes, expects exactly 1000 records, and proves IDs `worker-5` through
  `worker-1004` are retained.
- [x] Add assertions that mutating a returned entry cannot change a second
  snapshot, `limit=0` returns `[]`, and invalid limits raise `ValueError`.
- [x] Run `python -m unittest tests.test_terminal_worker` and confirm the new
  assertions fail because 1005 entries are retained or returned dictionaries
  alias storage.
- [x] Add `TERMINAL_AUDIT_LIMIT = 1000`, a fixed-capacity deque, an audit lock,
  locked append/snapshot/clear operations, copied dictionaries, and exact
  non-negative integer limit validation.
- [x] Re-run `python -m unittest tests.test_terminal_worker` and confirm all
  Worker tests pass without warnings.

### Task 2: Apply the same invariant to TerminalExecutor

**Files:**
- Modify: `tests/test_terminal_executor_extended_v2.py`
- Modify: `src/core/kernel/terminal_executor.py`

**Interfaces:**
- Consumes: `TerminalExecutor.execute()`, `get_audit_log()`, and
  `clear_audit_log()`.
- Produces: the same capacity, validation, and snapshot semantics as the
  Worker.

- [x] Add a test using a patched `_run_command` to execute 1005 allowed calls,
  then assert oldest-entry eviction, newest-entry retention, snapshot
  isolation, zero limit, invalid limits, and clear behavior.
- [x] Run the focused executor module and confirm the new assertions fail for
  unbounded retention or mutable snapshot aliasing.
- [x] Replace the executor list with a fixed-capacity deque, add an audit lock,
  centralize locked recording, and protect getter/clear operations.
- [x] Update the obsolete internal list-shape test to assert the public bounded
  contract rather than a private container type.
- [x] Re-run all terminal-focused modules and confirm they pass.

### Task 3: Review, document, and verify

**Files:**
- Modify: `tests/run_all.py`
- Modify: `tests/test_run_all_coverage.py`
- Modify: `AGENTS.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/reports/PROJECT_ANALYSIS.md`
- Modify: `docs/reports/README.md`
- Create: `docs/reports/AUDIT_REPORT_157.md`
- Remove: `docs/reports/AUDIT_REPORT_147.md`

**Interfaces:**
- Consumes: focused RED/GREEN evidence and repository validation commands.
- Produces: canonical aggregate coverage and Iteration 157 delivery evidence.

- [x] Register the existing `TestTerminalExecutorAuditLog` class exactly once
  in the aggregate suite and verify the aggregate coverage guard.
- [x] Self-review retention, ordering, locking, copied snapshots, validation,
  unchanged execution paths, and diff scope.
- [x] Run aggregate/discovery Python suites, compileall, Ruff, Vitest,
  Playwright, typecheck, build, required-services integration, and
  `git diff --check`.
- [x] Update iteration evidence and roll the audit window from 147-156 to
  148-157 only after measured counts are known.
- [x] Run final ledger, report-count, scratch-directory, listener, plan, and
  Git status guards.
