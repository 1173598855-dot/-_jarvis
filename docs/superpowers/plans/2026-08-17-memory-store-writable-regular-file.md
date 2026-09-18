# MemoryStore Writable Regular-File Boundary Implementation Plan

> Execute inline in this session. Do not dispatch subagents, stage, or commit;
> the worktree contains overlapping user changes.

**Goal:** Prevent writable MemoryStore list and probe deletion paths from
following symlink or reparse candidates outside the configured directory.

### Task 1: TDD regressions and shared safe reader

- [x] Add real symlink regressions for writable load and probe deletion.
- [x] Run them and observe external entry loading plus accepted link deletion
  with the old implementation (RED).
- [x] Reuse `lstat`, reparse checks, `O_NOFOLLOW`, and descriptor identity
  validation for writable candidates.
- [x] Preserve writable universal-newline semantics after descriptor reads.
- [x] Re-run both regressions and all MemoryStore tests.

### Task 2: Delivery evidence

- [x] Run warning-enabled affected regressions and all project gates.
- [x] Self-review path identity, mutation ordering, compatibility, and diff
  scope.
- [x] Update Iteration 173 ledgers and roll the report window to 164-173.
