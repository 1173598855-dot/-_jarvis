# Python Dependency Lock Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one universal, hash-enforced Python dependency lock and make CI consume it without changing runtime behavior.

**Architecture:** Resolve `pyproject.toml` default plus `dev` dependencies with pinned `uv==0.12.5` into `requirements.lock`, then install the third-party graph with pip `--require-hashes` before installing the local project with `--no-deps --no-build-isolation -e .`. Setuptools is both the declared build backend and a locked dev dependency, so editable installation cannot create a second floating build environment. An offline guard uses `tomllib` or the declared Python 3.10 `tomli` backport, compares direct dependency names, validates every locked block, and prevents CI from bypassing the lock.

**Tech Stack:** Python 3.10+ metadata, `uv==0.12.5`, pip hash checking, TOML, unittest, GitHub Actions.

## Global Constraints

- Preserve the `requires-python = ">=3.10"` floor and existing dependency lower bounds.
- Generate one universal lock for the default and `dev` groups with SHA-256 hashes.
- Do not record an index URL, trusted host, VCS source, local path, editable requirement, or archive URL.
- Do not add runtime behavior, API, authorization, Worker, or frontend changes.
- Do not stage, commit, reset, clean, or revert the mixed worktree.

---

### Task 1: Dependency Lock Contract

**Files:**
- Create: `tests/test_python_dependency_lock.py`
- Modify: `tests/run_all.py`
- Modify: `tests/test_run_all_coverage.py`

**Interfaces:**
- Consumes: `pyproject.toml` dependency and optional `dev` arrays
- Produces: offline assertions over `requirements.lock` and CI install commands

- [x] **Step 1: Write the failing lock tests**

Add tests for lock existence, the exact universal generator header, direct
dependency coverage, unique normalized exact pins, per-block SHA-256 hashes,
forbidden source directives, and lock-based CI commands.

- [x] **Step 2: Run the focused suite and verify RED**

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_python_dependency_lock -v
```

Expected: failure because `requirements.lock` does not exist.

- [x] **Step 3: Register the suite once in the aggregate runner**

Add `TestPythonDependencyLock` to `AGGREGATE_TEST_CASES` and its uniqueness
guard to `test_run_all_coverage.py`.

### Task 2: Universal Hash Lock

**Files:**
- Create mechanically: `requirements.lock`

**Interfaces:**
- Consumes: `pyproject.toml`, universal Python 3.10+ resolution
- Produces: exact third-party pins and accepted distribution hashes

- [x] **Step 1: Install only the pinned lock generator locally**

```powershell
.\venv\Scripts\python.exe -m pip install uv==0.12.5
```

- [x] **Step 2: Generate the lock**

```powershell
.\venv\Scripts\uv.exe pip compile pyproject.toml --extra dev --universal --python-version 3.10 --generate-hashes --no-sources --custom-compile-command "uv==0.12.5 pip compile pyproject.toml --extra dev --universal --python-version 3.10 --generate-hashes --no-sources --output-file requirements.lock" --output-file requirements.lock
```

- [x] **Step 3: Run the focused suite and verify GREEN**

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_python_dependency_lock -v
```

Expected: every lock-shape test except the not-yet-updated CI assertion passes.

### Task 3: CI And Setup Consumption

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `tests/test_ci_workflow.py`
- Modify: `README.md`
- Modify: `docs/SETUP.md`
- Modify: `docs/DEVELOPMENT_GUIDE.md`

**Interfaces:**
- Consumes: `requirements.lock`
- Produces: hash-enforced CI and documented install/regeneration workflows

- [x] **Step 1: Update CI to install the lock**

Use `python -m pip install --require-hashes -r requirements.lock` in both
Python jobs. Install the local project with
`python -m pip install --no-deps --no-build-isolation -e .` only in
`python-contracts`; remove floating Ruff and `.[dev]` resolution.

- [x] **Step 2: Update CI and lock guard tests**

Require both exact commands, reject the two old floating commands, and retain
all existing verification-command assertions.

- [x] **Step 3: Document locked setup and regeneration**

Make the lock the default repository-development install path. Preserve
`pip install -e ".[dev]"` only as an explicitly unlocked package-development
alternative, and document the exact pinned `uv` regeneration command.

- [x] **Step 4: Run focused guards**

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_python_dependency_lock tests.test_ci_workflow tests.test_docs_setup tests.test_readme tests.test_run_all_coverage -v
```

Expected: all tests pass.

### Task 4: Isolated Install And Full Evidence

**Files:**
- Modify: `AGENTS.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/reports/PROJECT_ANALYSIS.md`
- Modify: `docs/reports/README.md`
- Create: `docs/reports/AUDIT_REPORT_150.md`
- Delete: `docs/reports/AUDIT_REPORT_140.md`
- Modify: `docs/superpowers/plans/2026-08-17-python-dependency-lock.md`

**Interfaces:**
- Consumes: final lock, CI, docs, and fresh verification results
- Produces: Iteration 150 evidence and rolling audit window 141-150

- [x] **Step 1: Verify a clean hash-enforced install**

Create a fresh temporary virtual environment, install `requirements.lock`
with `--require-hashes`, install the repository with
`--no-deps --no-build-isolation -e .`, import
`fastapi`, `uvicorn`, `requests`, and `psutil`, then remove only that verified
temporary directory.

- [x] **Step 2: Run complete project gates**

Run aggregate and discovery suites, compileall, Ruff, Vitest, Playwright,
typecheck, build, deterministic local integration, and `git diff --check`.

- [x] **Step 3: Perform an independent diff review**

Check dependency completeness, universal markers, hash presence, CI command
ordering, docs consistency, and that no runtime source changed for this
iteration.

- [x] **Step 4: Update Iteration 150 evidence**

Record exact test totals and lock package count, update the current P1 list,
advance the ten-report window to 141-150, and mark this plan complete.

- [x] **Step 5: Run final guards**

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_python_dependency_lock tests.test_ci_workflow tests.test_iteration_ledger tests.test_docs_setup tests.test_readme tests.test_project_config -v
.\venv\Scripts\python.exe -m ruff check src tests scripts
git diff --check
git status --short
```

Expected: all guards pass, Ruff has zero findings, whitespace is clean, and no
unrelated path was staged, committed, reset, cleaned, or reverted.
