# Bounded Run-State Cleanup Entries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bound both descriptor-relative run-state cleanup directory scans before any deletion occurs.

**Architecture:** Add a descriptor-scanning capability gate and a private bounded name collector based on `os.scandir(fd)`. Route revision pruning and flat-directory deletion through complete bounded snapshots while retaining every existing no-follow open and identity recheck.

**Tech Stack:** Python standard library (`os.scandir`, descriptor-relative filesystem APIs, `unittest`), existing FileRunStateRepository.

## Global Constraints

- Revision cleanup accepts at most `8_192` direct entries.
- Flat recovery directories accept at most the six values in `_FILE_NAMES`.
- Reject the first excess entry before retaining it or performing deletion.
- Cleanup overflow and scan errors retain data and do not fail an otherwise committed operation.
- Preserve unrelated working-tree changes and add no dependencies.

---

### Task 1: Add cleanup budget regressions

**Files:**
- Modify: `tests/test_file_run_state_repository.py`

**Interfaces:**
- Consumes: `FileRunStateRepository._prune_revision_snapshots()` and `_discard_flat_directory()`.
- Produces: expected contract for `_bounded_fd_directory_names(directory_fd: int, limit: int) -> tuple[str, ...]`.

- [x] **Step 1: Write a guarded-scanner test**

  Patch `os.scandir` with an iterator returning three descriptor entries and
  assert a limit of two raises `RunStateIntegrityError` after exactly three
  `next()` calls.

- [x] **Step 2: Write no-partial-cleanup tests**

  Patch the new helper to raise on revisions and flat-directory snapshots;
  assert `_discard_flat_directory`, `os.unlink`, and `os.rmdir` are not called.

- [x] **Step 3: Verify RED**

  Run `python -m unittest tests.test_file_run_state_repository` and confirm the
  failures are caused by the missing helper and unhandled cleanup overflow.

### Task 2: Implement bounded descriptor scans

**Files:**
- Modify: `src/adapters/file_run_state_repository.py`

**Interfaces:**
- Consumes: caller-owned readable directory descriptor and fixed integer limit.
- Produces: `_bounded_fd_directory_names(directory_fd, limit)` returning a complete bounded tuple without closing the caller descriptor.

- [x] **Step 1: Extend the capability gate**

  Require `os.scandir in os.supports_fd` in `_supports_safe_fd_cleanup()`.

- [x] **Step 2: Add the bounded helper**

  Validate the non-negative integer limit, iterate `os.scandir(directory_fd)`
  in a context manager, append only `entry.name`, and raise the stable
  `too many cleanup directory entries` integrity error before retaining the
  first overflow entry.

- [x] **Step 3: Route both cleanup call sites**

  Collect the revision-root snapshot with the 8,192 limit and each flat
  snapshot with the six-file limit. Treat helper integrity failures like the
  existing best-effort `OSError` cleanup failures.

- [x] **Step 4: Verify GREEN**

  Run the focused repository suite, targeted Ruff and targeted compileall.

### Task 3: Self-review and synchronize evidence

**Files:**
- Modify: `AGENTS.md`, `CHANGELOG.md`, `docs/DEVELOPMENT_GUIDE.md`, `docs/reports/PROJECT_ANALYSIS.md`, `docs/reports/README.md`
- Create: `docs/reports/AUDIT_REPORT_212.md`
- Remove from rolling window: `docs/reports/AUDIT_REPORT_202.md`

**Interfaces:**
- Consumes: fresh test and build output.
- Produces: Iteration 212 current-state and audit evidence.

- [x] **Step 1: Review the task diff**

  Recheck exact-limit behavior, no-partial-delete ordering, descriptor
  ownership, identity checks, platform capability gating and unrelated diff.

- [x] **Step 2: Run full verification**

  Run aggregate and discovery Python tests, compileall, Ruff, required-services
  integration, Vitest, typecheck, build, Playwright, ledger checks and
  `git diff --check`.

- [x] **Step 3: Update current documentation**

  Record actual totals, move the rolling report window to Iterations 203-212,
  then rerun ledger and diff checks after every correction.
