# MemoryStore Index Encoding Implementation Plan

> **For agentic workers:** Execute inline in this session. Do not dispatch
> subagents, stage, or commit because the shared worktree contains overlapping
> user changes.

**Goal:** Keep untrusted title and summary text inside one deterministic
MemoryStore Markdown index row.

**Architecture:** Encode control characters and link-label delimiters before
building the row, and reuse the encoded title for exact replacement matching.

**Tech Stack:** Python 3.10+, Markdown text encoding, `unittest`.

## Global Constraints

- Preserve original MemoryEntry values, IDs, entry files, and HTTP contracts.
- Preserve the existing index row layout and 100-character raw summary bound.
- Keep directory transaction ownership unchanged.
- Use TDD and observe physical row injection before implementation.
- Do not stage or commit the mixed worktree.

---

### Task 1: Prove and fix index row injection

**Files:**
- Modify: `tests/test_context_compressor.py`
- Modify: `src/core/brain/context_compressor.py`

- [x] Add a control/bracket injection regression to registered TestMemoryStore.
- [x] Run it and confirm the old formatter creates extra physical rows.
- [x] Add deterministic inline and link-label encoding.
- [x] Verify unsafe exact-title updates replace one encoded row.
- [x] Re-run all context-compressor tests.

### Task 2: Delivery evidence

**Files:**
- Modify: `AGENTS.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/reports/PROJECT_ANALYSIS.md`
- Modify: `docs/reports/README.md`
- Create: `docs/reports/AUDIT_REPORT_168.md`
- Remove: `docs/reports/AUDIT_REPORT_158.md`

- [x] Run warning-enabled service regressions.
- [x] Self-review encoding, exact matching, compatibility, and diff scope.
- [x] Run all Python, frontend, integration, and repository gates.
- [x] Update Iteration 168 ledgers and roll the report window to 159-168.
