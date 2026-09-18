# TerminalExecutor Shell Parse Failure Implementation Plan

> Execute inline in this session. Do not dispatch subagents, stage, or commit;
> the worktree contains overlapping user changes.

**Goal:** Normalize malformed direct `TerminalExecutor.execute_shell()` input
to a bounded failed result.

### Task 1: TDD regression and minimal boundary

- [x] Add a registered unmatched-quote shell regression.
- [x] Run it and observe `ValueError: No closing quotation` escaping (RED).
- [x] Catch shell tokenization `TypeError`/`ValueError` and return the existing
  failed result shape without launching a process.
- [x] Re-run the regression and the terminal executor extended suite.

### Task 2: Delivery evidence

- [x] Run warning-enabled affected regressions and all project gates.
- [x] Self-review exception scope, result shape, process/audit behavior, and
  diff scope.
- [x] Update Iteration 175 ledgers and roll the report window to 166-175.
