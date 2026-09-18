# MemoryStore Frontmatter Encoding Implementation Plan

> Execute inline in this session. Do not dispatch subagents, stage, or commit;
> the worktree contains overlapping user changes.

**Goal:** Preserve MemoryStore string frontmatter values across delimiters and
newlines while keeping old files readable.

### Task 1: TDD regression and compatible parser

- [x] Add a registered round-trip regression for title/body delimiters.
- [x] Run it and observe title truncation with the old formatter (RED).
- [x] Encode unsafe string frontmatter values as JSON scalars while preserving
  ordinary unquoted formatting.
- [x] Parse complete delimiter lines and decode new values with a legacy
  unquoted fallback.
- [x] Reuse decoded frontmatter for probe deletion and rerun MemoryStore tests.

### Task 2: Delivery evidence

- [x] Run warning-enabled affected regressions and all project gates.
- [x] Self-review format compatibility, parser boundaries, probe lifecycle, and
  diff scope.
- [x] Update Iteration 170 ledgers and roll the report window to 161-170.
