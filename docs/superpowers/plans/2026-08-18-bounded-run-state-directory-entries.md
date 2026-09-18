# Bounded Run-State Directory Entries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bound FileRunStateRepository recovery-directory entry collection and fail closed before unbounded `iterdir()` materialization.

**Architecture:** Add a Loader-owned `os.scandir()` helper with a strict entry budget, then route run-root probing, unpublished revision recovery, and published revision file-set verification through it. Preserve the descriptor-relative cleanup path and all existing file-byte budgets.

**Tech Stack:** Python standard library (`os.scandir`, `pathlib`, `unittest`), existing FileRunStateRepository and iteration ledger.

## Global Constraints

- `MAX_RECOVERY_DIRECTORY_ENTRIES` is exactly `8_192`.
- Reject the first entry beyond each requested limit before retaining it.
- Never return partial recovery state after an entry overflow.
- Preserve valid archive, revision, retry and POSIX cleanup semantics.
- Do not add dependencies or alter unrelated user changes.

---

### Task 1: Add failing directory-budget regressions

**Files:**
- Modify: `tests/test_file_run_state_repository.py`

- [ ] **Step 1: Assert the fixed budget and overflow behavior**

  Add tests for the 8,192 constant, an unpublished revision directory that
  exceeds a patched budget, and a guarded scanner that must stop after exactly
  `limit + 1` entries.

- [ ] **Step 2: Run the focused suite to verify RED**

  Run `venv\\Scripts\\python.exe -m unittest tests.test_file_run_state_repository`.
  Expected: the new tests fail because the helper and budget do not yet exist.

### Task 2: Implement the bounded helper and call sites

**Files:**
- Modify: `src/adapters/file_run_state_repository.py`

- [ ] **Step 1: Add `_bounded_directory_children`**

  Use a context-managed `os.scandir()` loop, retain at most the requested
  `Path` entries, and raise `RunStateIntegrityError` before appending the first
  overflow entry or when the directory cannot be read.

- [ ] **Step 2: Replace unbounded recovery probes**

  Use a two-entry run-root limit, the 8,192 revision-child limit in
  `_can_resume_unpublished_revision`, and a six-entry limit in
  `_verify_revision_contents`. Keep descriptor-relative cleanup unchanged.

- [ ] **Step 3: Run focused GREEN checks**

  Run the repository suite, targeted Ruff and targeted compileall. All must
  exit zero with only the two documented platform skips.

### Task 3: Run project verification and synchronize evidence

**Files:**
- Modify: `AGENTS.md`, `CHANGELOG.md`, `docs/DEVELOPMENT_GUIDE.md`,
  `docs/reports/PROJECT_ANALYSIS.md`, `docs/reports/README.md`
- Create: `docs/reports/AUDIT_REPORT_208.md`
- Delete: `docs/reports/AUDIT_REPORT_198.md`

- [ ] **Step 1: Run aggregate, discovery, compileall, Ruff and integration**

  Record fresh totals, then run the iteration ledger and `git diff --check`.

- [ ] **Step 2: Update current-state documentation**

  Record Iteration 208, the fixed directory boundary, the real test totals and
  the rolling window 199-208.

- [ ] **Step 3: Re-run ledger and relevant tests after every correction**

  Any documentation mismatch is fixed before the iteration is considered
  verified.
