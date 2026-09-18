# MemoryStore Mutation Ownership Implementation Plan

> **For agentic workers:** Execute inline in this session. Do not dispatch
> subagents, stage, or commit because the shared worktree contains overlapping
> user changes.

**Goal:** Make one writable MemoryStore present coherent entry/index state
under concurrent HTTP operations.

**Architecture:** A per-instance `threading.RLock` owns store, probe delete,
legacy load, and consolidate transactions. Read-only scanning remains lock-free
and bounded by its existing filesystem controls.

**Tech Stack:** Python 3.10+, `threading.RLock`, `pathlib`, `unittest.mock`.

## Global Constraints

- Preserve memory file and `MEMORY.md` formats.
- Do not serialize independent MemoryStore instances or read-only role scans.
- Keep semantic compression work local to the existing consolidate call.
- Use TDD and observe duplicate index rows first.
- Do not stage or commit the mixed worktree.

---

### Task 1: Prove index transaction race

**Files:**
- Modify: `tests/test_context_compressor.py`

- [x] Add deterministic same-title concurrent store regression.
- [x] Assert both entry files remain and the index has one title row.
- [x] Run the focused test and confirm expected failure.

### Task 2: Implement mutation ownership

**Files:**
- Modify: `src/core/brain/context_compressor.py`

- [x] Add a per-instance reentrant mutation lock.
- [x] Serialize store and probe-delete transactions.
- [x] Serialize writable loads and consolidate with the same lock.
- [x] Run all context-compressor and HTTP memory tests, compileall, and Ruff.

### Task 3: Delivery evidence

**Files:**
- Modify: `AGENTS.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/reports/PROJECT_ANALYSIS.md`
- Modify: `docs/reports/README.md`
- Create: `docs/reports/AUDIT_REPORT_165.md`
- Remove: `docs/reports/AUDIT_REPORT_155.md`

- [x] Confirm the registered MemoryStore class contributes the regression.
- [x] Self-review lock scope, reentrancy, read-only paths, and diff.
- [x] Run all Python, frontend, integration, and repository consistency gates.
- [x] Update Iteration 165 ledgers and roll the report window to 156-165.
