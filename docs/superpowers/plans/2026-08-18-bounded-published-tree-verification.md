# Bounded Published Tree Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bound FileCapabilityStore published-payload drift verification without changing revision integrity or lifecycle contracts.

**Architecture:** Replace `os.walk()` with an explicit `os.scandir()` stack. Count entries before pushing or descending, close each iterator with a context manager, and retain only a bounded directory stack.

**Tech Stack:** Python standard library `os`, `pathlib`, `unittest`, `unittest.mock`.

## Global Constraints

- Published revisions remain content-addressed, disabled, and fail-closed on drift.
- No archive, URL, filesystem path, or lifecycle HTTP input is added.
- Existing `REVISION_DRIFT`, `STORE_STATE_INVALID`, and public repository contracts remain stable.

---

### Task 1: Bound Published Payload Traversal

**Files:**
- Modify: `src/adapters/file_capability_store.py`
- Test: `tests/test_file_capability_store.py`

**Interfaces:**
- Consumes: `CapabilityPackageLimits.max_files` and the verified revision's
  `payload` directory.
- Produces: bounded `_verify_published_content()` traversal.

- [x] **Step 1: Write the failing test**

  Create three extra payload directories in a store limited to two entries and
  patch `os.scandir` with an iterator that raises if a third item is requested.
  Rebuild must report `REVISION_DRIFT` after consuming only the file and first
  extra directory.

- [x] **Step 2: Run test to verify it fails**

  Run: `python -m unittest tests.test_file_capability_store.TestFileCapabilityStore.test_rebuild_stops_scandir_at_first_published_entry_over_limit -v`

  Expected: FAIL because `os.walk()` consumes the complete directory before
  yielding it to the adapter.

- [x] **Step 3: Write minimal implementation**

  Traverse with a LIFO `Path` stack and `with os.scandir(...)`; check path
  ownership, entry count, symlink/type, directory descent, and expected-file
  membership one item at a time.

- [x] **Step 4: Run tests to verify it passes**

  Run: `python -m unittest tests.test_file_capability_store -v`

  Expected: all 49 FileCapabilityStore tests PASS.

- [ ] **Step 5: Review the diff and run repository verification**

  Run the aggregate/discovery Python suites, Ruff, compileall, frontend
  Vitest/Playwright/typecheck/build, required-services integration, and
  `git diff --check`; record exact results in the iteration report.
