# Bounded Capability Registry Reads Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce the capability registry's existing file budgets before allocation, parsing, and hashing.

**Architecture:** Add one module-local bounded byte reader and reuse it for Skill metadata, Plugin JSON, and tree hashing. Normalize JSON parser resource errors through the existing invalid Plugin record boundary.

**Tech Stack:** Python 3.10+, standard `pathlib`, `json`, `hashlib`, and `unittest`.

## Global Constraints

- Keep `_MAX_FILE_BYTES` exactly `1024 * 1024` and `_MAX_TOTAL_BYTES` exactly `4 * 1024 * 1024`.
- No content read may use a negative/unbounded size.
- Stable-file digest output and every public capability/API shape remain unchanged.
- Work in the current mixed checkout without staging or committing files.

---

### Task 1: Reproduce pre-limit reads and parser escape

**Files:**
- Modify: `tests/test_capability_registry.py`

**Interfaces:**
- Consumes: `CapabilityRegistry.snapshot() -> CapabilitySnapshot`
- Consumes: module-private `_hash_file(path: Path) -> str`
- Produces: three deterministic resource-boundary regressions

- [ ] **Step 1: Guard registry content reads**

Wrap `Path.open` for the fixture snapshot and reject non-binary modes or
negative read sizes. Assert the public snapshot remains equal to the unguarded
snapshot.

- [ ] **Step 2: Verify RED**

Run the guarded-read test. Expected: FAIL when `SKILL.md` reaches
`Path.read_text()` and calls an unbounded text read.

- [ ] **Step 3: Reproduce hash growth beyond stat**

Create a file larger than `_MAX_FILE_BYTES`, patch its stat result to report a
small regular file, and assert `_hash_file()` raises
`CapabilityValidationError` with `tree_file_too_large`.

- [ ] **Step 4: Verify RED**

Run the hash-growth test. Expected: FAIL because current hashing reads through
EOF and returns a digest.

- [ ] **Step 5: Reproduce parser resource errors**

Create separate Plugin Manifests containing 5,000 nested arrays and a 5,000
digit integer, each below 1 MiB. Assert each scan returns an invalid record for
that directory and still returns the valid `event-logger` Plugin.

- [ ] **Step 6: Verify RED**

Run the parser test. Expected: ERROR as `RecursionError` or `ValueError`
escapes `snapshot()`.

### Task 2: Route content through one bounded reader

**Files:**
- Modify: `src/core/kernel/capability_registry.py`
- Test: `tests/test_capability_registry.py`

**Interfaces:**
- Produces: `_read_bounded_file(path: Path, *, code: str, message: str) -> bytes`

- [ ] **Step 1: Implement the reader**

Check `path.stat().st_size`, open `rb`, read `_MAX_FILE_BYTES + 1`, and raise
the caller-selected `CapabilityValidationError` if either observed size exceeds
the existing limit.

- [ ] **Step 2: Reuse bounded bytes**

Decode Skill and Plugin metadata from the helper. Make `_hash_files()` obtain
each file's bytes through the helper, use `len(content)` for the per-tree total
and digest length field, then hash the content.

- [ ] **Step 3: Normalize JSON resources**

Add `RecursionError` and `ValueError` to the Plugin candidate exception
boundary and retain the existing `manifest_invalid` issue code.

- [ ] **Step 4: Verify GREEN**

Run all three regressions and capability/API impact suites. Expected: finite
binary reads, bounded hash failure, invalid parser records, and unchanged valid
snapshots.

### Task 3: Deliver Iteration 184 evidence

**Files:**
- Modify: `AGENTS.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/DEVELOPMENT_GUIDE.md`
- Modify: `docs/reports/PROJECT_ANALYSIS.md`
- Modify: `docs/reports/README.md`
- Create: `docs/reports/AUDIT_REPORT_184.md`
- Delete: `docs/reports/AUDIT_REPORT_174.md`

**Interfaces:**
- Consumes: observed verification output
- Produces: rolling audit window 175-184 and current test baseline

- [ ] **Step 1: Run all project gates**

Run aggregate, discovery, compileall, Ruff, Vitest, Playwright, typecheck,
build, required-services integration, ledger guards, and `git diff --check`.

- [ ] **Step 2: Update current evidence**

Record only observed counts and results. Preserve the explicit directory
enumeration, same-user race, Plugin execution, and OS sandbox scope boundaries.
