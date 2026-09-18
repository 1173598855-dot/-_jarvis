# MemoryStore Exact Index Title Implementation Plan

> **For agentic workers:** Execute inline in this session. Do not dispatch
> subagents, stage, or commit because the shared worktree contains overlapping
> user changes.

**Goal:** Prevent substring-related MemoryStore index row replacement while
preserving exact-title updates.

**Architecture:** Compare each Markdown row against one exact link-label
prefix, replace matching rows, and append only when none match.

**Tech Stack:** Python 3.10+, `pathlib`, `unittest`.

## Global Constraints

- Preserve public MemoryStore and HTTP contracts.
- Preserve existing Markdown row format.
- Keep the directory transaction lock unchanged.
- Use TDD and observe the substring collision first.
- Do not stage or commit the mixed worktree.

---

### Task 1: Prove and fix exact matching

**Files:**
- Modify: `tests/test_context_compressor.py`
- Modify: `src/core/brain/context_compressor.py`

- [x] Add a prefix-title collision regression.
- [x] Run it and confirm the old substring logic loses the longer-title row.
- [x] Implement exact link-label prefix matching.
- [x] Re-run exact-title replacement and all MemoryStore tests.

### Task 2: Delivery evidence

**Files:**
- Modify: `AGENTS.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/reports/PROJECT_ANALYSIS.md`
- Modify: `docs/reports/README.md`
- Create: `docs/reports/AUDIT_REPORT_167.md`
- Remove: `docs/reports/AUDIT_REPORT_157.md`

- [x] Run warning-enabled service regressions.
- [x] Self-review matching semantics, newline preservation, and diff scope.
- [x] Run all Python, frontend, integration, and repository gates.
- [x] Update Iteration 167 ledgers and roll the report window to 158-167.
