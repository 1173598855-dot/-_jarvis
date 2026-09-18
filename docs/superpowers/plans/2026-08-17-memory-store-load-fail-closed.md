# MemoryStore Writable Load Fail-Closed Implementation Plan

> Execute inline in this session. Do not dispatch subagents, stage, or commit;
> the worktree contains overlapping user changes.

**Goal:** Keep one malformed legacy MemoryStore entry from aborting writable
`load()` while preserving valid entries and existing contracts.

### Task 1: TDD regression and minimal fix

- [x] Add a registered writable-load test with malformed and valid frontmatter.
- [x] Run the test and observe the existing parse exception (RED).
- [x] Catch only known file/metadata parsing failures at the legacy file
  boundary and skip the damaged candidate (GREEN).
- [x] Re-run all `TestMemoryStore` cases.

### Task 2: Delivery evidence

- [x] Run warning-enabled affected regressions and all project gates.
- [x] Self-review exception scope, ordering, lock ownership, and diff scope.
- [x] Update Iteration 169 ledgers and roll the report window to 160-169.
