# MemoryStore Unicode Frontmatter Line Separator Implementation Plan

> Execute inline in this session. Do not dispatch subagents, stage, or commit;
> the worktree contains overlapping user changes.

**Goal:** Preserve NEL and Unicode line/paragraph separators inside newly
written MemoryStore frontmatter strings.

### Task 1: TDD regression and minimal encoding fix

- [x] Add a registered title round-trip regression containing U+0085, U+2028,
  and U+2029.
- [x] Run it and observe the old implementation truncating the quoted title
  (RED).
- [x] Translate only those physical line separators to JSON Unicode escapes
  after Unicode-preserving scalar encoding.
- [x] Re-run the regression and all MemoryStore tests.

### Task 2: Delivery evidence

- [x] Run warning-enabled affected regressions and all project gates.
- [x] Self-review JSON compatibility, parser boundaries, and diff scope.
- [x] Update Iteration 172 ledgers and roll the report window to 163-172.
