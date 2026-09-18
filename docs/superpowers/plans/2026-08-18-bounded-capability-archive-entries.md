# Bounded Capability Archive Entries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep capability archive metadata validation and publication within the configured entry bound without changing package behavior.

**Architecture:** Reuse `ZipFile.filelist`, which is already parsed by the standard-library reader, after checking its length against `CapabilityPackageLimits.max_files`. Keep logical path types in one bounded mapping and validate conflicts after the existing metadata size checks.

**Tech Stack:** Python standard library `zipfile`, `unittest`, `unittest.mock`.

## Global Constraints

- Package bytes are caller-provided and remain read-only; no archive, URL, path, or lifecycle HTTP input is added.
- Validated capabilities remain disabled and are never imported or executed.
- Existing `CapabilityStoreError` codes and publication/retry contracts remain stable.

---

### Task 1: Bound Archive Metadata Enumeration

**Files:**
- Modify: `src/adapters/file_capability_store.py`
- Test: `tests/test_file_capability_store.py`

**Interfaces:**
- Consumes: `CapabilityPackageLimits.max_files` and `zipfile.ZipFile.filelist`.
- Produces: `FileCapabilityStore._bounded_archive_entries()` and bounded
  archive verification/publication behavior.

- [x] **Step 1: Write the failing test**

  Patch `zipfile.ZipFile.infolist` to raise while installing a valid package;
  the install must still return the expected disabled revision.

- [x] **Step 2: Run test to verify it fails**

  Run: `python -m unittest tests.test_file_capability_store.TestFileCapabilityStore.test_install_does_not_copy_archive_entries_through_infolist -v`

  Expected: FAIL at `_verify_archive()` because the old implementation calls
  `archive.infolist()`.

- [x] **Step 3: Write minimal implementation**

  Add `_bounded_archive_entries()` to read `archive.filelist`, reject malformed
  metadata as `ARCHIVE_INVALID`, reject `len(filelist) > max_files` as
  `ARCHIVE_FILE_LIMIT`, and use the helper in verification and publication.
  Replace the second logical-entry list with a bounded path-type mapping while
  retaining conflict validation after size checks.

- [x] **Step 4: Run tests to verify it passes**

  Run: `python -m unittest tests.test_file_capability_store -v`

  Expected: all FileCapabilityStore tests PASS.

- [x] **Step 5: Review the diff and run repository verification**

  Run the targeted suite, aggregate/discovery Python suites, Ruff, compileall,
  frontend Vitest/typecheck/build/Playwright, required-services integration,
  and `git diff --check`; record exact results in the iteration report.
