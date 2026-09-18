# MemoryStore Descriptor Read Failure Isolation Implementation Plan

> Execute inline in this session. Do not dispatch subagents, stage, or commit;
> the worktree contains overlapping user changes.

**Goal:** Keep a post-open MemoryStore descriptor I/O error from aborting a
bounded read-only scan.

### Task 1: TDD regression and bounded I/O failure

- [x] Add a registered two-candidate read-only regression with an injected
  first `os.read` failure.
- [x] Run it and observe the old implementation surfacing `OSError` (RED).
- [x] Return a rejected candidate plus actual consumed bytes for descriptor
  `OSError` while retaining unconditional close.
- [x] Re-run the regression and all MemoryStore tests.

### Task 2: Delivery evidence

- [x] Run warning-enabled affected regressions and all project gates.
- [x] Self-review descriptor ownership, byte accounting, compatibility, and
  diff scope.
- [x] Update Iteration 174 ledgers and roll the report window to 165-174.
