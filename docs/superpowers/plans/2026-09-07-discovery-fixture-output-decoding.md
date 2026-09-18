# Discovery Fixture Output Decoding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make discovery-runner end-to-end tests retain UTF-8 and arbitrary-byte diagnostics independently of the Windows host locale.

**Architecture:** Keep the production runner unchanged. Lock the test fixture's existing subprocess boundary to UTF-8 with `backslashreplace`, proven by one conflicting-locale regression and one undecodable-byte regression.

**Tech Stack:** Python 3.11 standard library, `unittest`, `unittest.mock`, existing discovery runner.

## Global Constraints

- Change only the discovery fixture, its tests and Iteration 247 documentation.
- Do not add dependencies or modify child/global encoding configuration.
- Preserve all unrelated dirty-worktree changes.
- Follow strict RED then GREEN evidence before broader verification.

---

### Task 1: Lock The Fixture Decoder Contract

**Files:**
- Modify: `tests/test_discover_tests_runner.py`

**Interfaces:**
- Consumes: `_DiscoveryFixtureMixin.run_script(arguments: list) -> tuple`.
- Produces: deterministic `CompletedProcess[str]` stdout/stderr with invalid
  bytes represented by `backslashreplace` escapes.

- [x] **Step 1: Add the locale-conflict regression**

Add a UTF-8 fixture with a non-ASCII docstring. Patch `locale.getencoding()` to
return `ascii`, set `PYTHONIOENCODING=utf-8` for the child and assert that
`run_script()` returns code zero plus the exact non-ASCII text.

- [x] **Step 2: Run RED**

Run:

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_discover_tests_runner.TestDiscoveryRunnerEndToEnd.test_run_script_decodes_utf8_independently_of_host_locale -v
```

Expected: FAIL because implicit `text=True` decoding loses or rejects the
UTF-8 output when the parent decoder is ASCII.

- [x] **Step 3: Add arbitrary-byte coverage**

Add a fixture that writes `b"invalid:\xff\n"` to stdout and assert that the
captured text contains the literal `invalid:\\xff` diagnostic.

- [x] **Step 4: Implement the minimal decoder fix**

Add these arguments to the existing `subprocess.run()` call:

```python
encoding="utf-8",
errors="backslashreplace",
```

- [x] **Step 5: Run GREEN**

Run the entire `tests.test_discover_tests_runner` module. Expected: all tests
pass without background reader-thread exceptions.

### Task 2: Verify And Record Iteration 247

**Files:**
- Modify: `AGENTS.md`
- Modify: `CHANGELOG.md`
- Modify: `README.md`
- Modify: `docs/reports/PROJECT_ANALYSIS.md`
- Modify: `docs/reports/README.md`
- Modify: `docs/reports/GITHUB_LEARNING_REPORT.md`
- Create: `docs/reports/AUDIT_REPORT_247.md`

**Interfaces:**
- Consumes: measured focused and aggregate verification.
- Produces: current-state evidence and report navigation for Iteration 247.

- [x] **Step 1: Run focused static and test gates**

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_discover_tests_runner tests.test_run_all_coverage -v
.\venv\Scripts\python.exe -m ruff check src tests scripts
.\venv\Scripts\python.exe -m compileall -q src tests scripts
```

- [x] **Step 2: Run aggregate and discovery gates**

```powershell
.\venv\Scripts\python.exe tests/run_all.py --timeout 1800 --json-report .test-run-all-247.json
.\venv\Scripts\python.exe scripts/discover_tests.py --timeout 1800 --json-report .test-discover-247.json
```

- [x] **Step 3: Update current-state evidence**

Record the exact totals, GitHub sources, selected no-dependency design and the
fact that production runner behavior is unchanged. Roll report navigation to
the newest ten reports without deleting unrelated worktree files.

- [x] **Step 4: Run final documentation and worktree checks**

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_iteration_ledger tests.test_readme tests.test_resume_document tests.test_docs_setup -v
git diff --check
git status --short
```
