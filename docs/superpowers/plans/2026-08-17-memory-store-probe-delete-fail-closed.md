# MemoryStore Probe Deletion Fail-Closed Implementation Plan

> Execute inline in this session. Do not dispatch subagents, stage, or commit;
> the worktree contains overlapping user changes.

**Goal:** Reject malformed MemoryStore probe candidates without surfacing
known parsing failures or deleting the candidate.

### Task 1: TDD regression and bounded failure handling

- [x] Add a registered malformed-frontmatter probe deletion regression.
- [x] Run it and observe `JSONDecodeError` from the old implementation (RED).
- [x] Catch known candidate read and frontmatter parse failures and return
  `False` before any mutation.
- [x] Keep unlink and index-update failures outside the rejection boundary.
- [x] Re-run the targeted regression and complete MemoryStore test class.

### Task 2: Delivery evidence

- [x] Run warning-enabled affected regressions and all project gates.
- [x] Self-review rejection behavior, valid deletion behavior, exception scope,
  and diff boundaries.
- [x] Update Iteration 171 ledgers and roll the report window to 162-171.
