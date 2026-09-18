# Bounded LLM Compression History Implementation Plan

> **For agentic workers:** Execute inline in this session. Do not dispatch
> subagents, stage, or commit because the shared worktree contains overlapping
> user changes.

**Goal:** Bound LLM compression audit state and give callers independent
history snapshots.

**Architecture:** A 1000-entry deque and one instance lock own all append,
snapshot, and clear operations. Records remain scalar dictionaries.

**Tech Stack:** Python 3.10+, `collections.deque`, `threading.Lock`, `unittest`.

## Global Constraints

- Preserve compression decisions, record fields, and oldest-to-newest reads.
- Do not hold the history lock during Ollama calls or heuristic compression.
- Use TDD and observe capacity and ownership regressions fail first.
- Do not stage or commit the mixed worktree.

---

### Task 1: Prove history capacity and ownership defects

**Files:**
- Modify: `tests/test_context_compressor_llm.py`

- [x] Add a deterministic 1005-record eviction regression.
- [x] Add a returned-record mutation regression.
- [x] Run the focused history tests and confirm expected failures.

### Task 2: Implement bounded synchronized history

**Files:**
- Modify: `src/core/brain/context_compressor.py`

- [x] Add the fixed history limit, deque, and instance lock.
- [x] Serialize append, snapshot, and clear operations.
- [x] Return independent record dictionaries.
- [x] Run all context-compressor tests, compileall, and focused Ruff.

### Task 3: Canonical coverage and delivery evidence

**Files:**
- Modify: `tests/run_all.py`
- Modify: `tests/test_run_all_coverage.py`
- Modify: `AGENTS.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/reports/PROJECT_ANALYSIS.md`
- Modify: `docs/reports/README.md`
- Create: `docs/reports/AUDIT_REPORT_161.md`
- Remove: `docs/reports/AUDIT_REPORT_151.md`

- [x] Register `TestLLMCompressorHistory` exactly once in the aggregate suite.
- [x] Self-review lock scope, capacity, snapshot ownership, and diff.
- [x] Run all Python, frontend, integration, and repository consistency gates.
- [x] Update Iteration 161 ledgers and roll the report window to 152-161.
