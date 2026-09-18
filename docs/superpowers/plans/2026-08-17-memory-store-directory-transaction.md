# MemoryStore Directory Transaction Implementation Plan

> **For agentic workers:** Execute inline in this session. Do not dispatch
> subagents, stage, or commit because the shared worktree contains overlapping
> user changes.

**Goal:** Keep entry files and `MEMORY.md` coherent across all cooperating
writable MemoryStore instances and processes sharing one directory.

**Architecture:** A weak process-local directory lock wraps a Windows named
mutex or POSIX lock file. Public operations own one outer transaction and call
explicit unlocked helpers for nested work.

**Tech Stack:** Python 3.10+, `threading.RLock`, Windows kernel mutexes, POSIX
`flock`, `multiprocessing` spawn, `unittest`.

## Global Constraints

- Preserve public MemoryStore and HTTP contracts.
- Preserve entry and `MEMORY.md` formats.
- Keep the read-only bounded scanner lock-free.
- Fail closed if OS coordination cannot be established.
- Use TDD and observe both races before implementation.
- Do not stage or commit the mixed worktree.

---

### Task 1: Prove separate-instance state loss

**Files:**
- Modify: `tests/test_context_compressor.py`

- [x] Add a deterministic two-instance stale-index schedule.
- [x] Confirm the old implementation loses one distinct title row.
- [x] Add a process-local canonical directory lock and verify GREEN.

### Task 2: Prove and fix cross-process state loss

**Files:**
- Modify: `src/core/brain/context_compressor.py`
- Modify: `tests/test_context_compressor.py`

- [x] Add a real spawn-process stale-index regression.
- [x] Confirm the process-local lock does not protect the second process.
- [x] Add Windows named-mutex and POSIX regular-file lock ownership.
- [x] Refactor nested writes to explicit unlocked helpers.
- [x] Run all context compressor tests, compileall, and focused Ruff.

### Task 3: Service and delivery evidence

**Files:**
- Modify: `AGENTS.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/reports/PROJECT_ANALYSIS.md`
- Modify: `docs/reports/README.md`
- Create: `docs/reports/AUDIT_REPORT_166.md`
- Remove: `docs/reports/AUDIT_REPORT_156.md`

- [x] Run warning-enabled HTTP and memory service regressions.
- [x] Self-review lock identity, ownership, failure paths, and diff scope.
- [x] Run all Python, frontend, integration, and repository consistency gates.
- [x] Update Iteration 166 ledgers and roll the report window to 157-166.
