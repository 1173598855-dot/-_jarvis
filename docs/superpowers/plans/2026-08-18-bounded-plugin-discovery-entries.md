# Bounded Plugin Discovery Entries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bound PluginLoader root discovery to 8,192 direct entries and reject an over-budget repository before any manifest read.

**Architecture:** Replace the unbounded `sorted(Path.iterdir())` materialization with a Loader-owned `os.scandir()` helper that stops at the first entry above the fixed budget. Build the complete bounded, sorted candidate list before manifest processing so overflow returns an empty, non-partial snapshot.

**Tech Stack:** Python standard library (`os.scandir`, `pathlib`, `unittest`), existing Plugin SDK and iteration ledger.

## Global Constraints

- `MAX_PLUGIN_DISCOVERY_ENTRIES` is exactly `8_192`.
- Count every direct plugin-root entry and reject strictly above the limit.
- Do not read a manifest or return a partial snapshot when the root is over budget.
- Preserve deterministic name ordering and existing per-candidate isolation at or below the limit.
- Preserve all unrelated user changes and do not add dependencies or lifecycle operations.

---

### Task 1: Add failing bounded-discovery regressions

**Files:**
- Modify: `tests/test_plugin_sdk.py`

**Interfaces:**
- Consumes: `PluginLoader.discover_plugins() -> list[PluginManifest]`
- Produces: regression coverage for exact-limit acceptance, first-overflow rejection, early iterator stop, and owned-snapshot replacement.

- [ ] **Step 1: Import the Plugin SDK module for a patched entry budget**

  Add `from core.kernel import plugin_sdk as plugin_sdk_module` without changing
  existing direct imports.

- [ ] **Step 2: Write the failing overflow tests**

  In the existing PluginLoader boundary test class, patch
  `plugin_sdk_module.MAX_PLUGIN_DISCOVERY_ENTRIES` to `2`. Build two valid
  plugins for the exact-limit case and three for overflow. Assert exact-limit
  IDs are name-sorted; assert overflow returns `[]`, `_read_bounded_manifest`
  is not called, a prior `_manifests` snapshot is cleared, and a guarded fake
  `os.scandir()` is advanced exactly three times rather than to a fourth entry.

- [ ] **Step 3: Run the focused tests and verify RED**

  Run `.\venv\Scripts\python.exe -m unittest tests.test_plugin_sdk`.
  Expected: the overflow cases fail because discovery still materializes every
  `Path.iterdir()` candidate and ignores the patched entry budget.

### Task 2: Implement the bounded root scan

**Files:**
- Modify: `src/core/kernel/plugin_sdk.py`

**Interfaces:**
- Produces: `MAX_PLUGIN_DISCOVERY_ENTRIES: int = 8_192`
- Produces: `PluginLoader._bounded_discovery_candidates() -> list[Path]`
- Preserves: `PluginLoader.discover_plugins() -> list[PluginManifest]`

- [ ] **Step 1: Add the fixed constant and bounded helper**

  Import `os`, define `MAX_PLUGIN_DISCOVERY_ENTRIES = 8_192`, and add a helper
  that owns `with os.scandir(self.plugins_dir) as entries`, appends at most the
  fixed number of `Path(entry.path)` values, raises `OverflowError` before
  appending the first excess entry, then sorts the bounded list by `path.name`.

- [ ] **Step 2: Make discovery reject overflow before manifest reads**

  Replace `sorted(self.plugins_dir.iterdir(), ...)` with the helper. Catch
  `OverflowError` separately, log the fixed candidate-limit failure, assign the
  fresh empty list to `_manifests`, and return it. Keep the existing `OSError`
  root failure and all per-candidate exception handling unchanged.

- [ ] **Step 3: Run focused Plugin SDK tests and verify GREEN**

  Run `.\venv\Scripts\python.exe -m unittest tests.test_plugin_sdk tests.test_plugin_sdk_extended tests.test_plugin_sdk_extended_v2 tests.test_plugin_installation`.
  Expected: all focused tests pass with no failure or error.

### Task 3: Self-review the bounded discovery change

**Files:**
- Review: `src/core/kernel/plugin_sdk.py`
- Review: `tests/test_plugin_sdk.py`

**Interfaces:**
- Consumes: the implementation and regression tests from Tasks 1-2.
- Produces: a scope-limited correctness and maintainability review.

- [ ] **Step 1: Review the implementation diff**

  Verify the scanner stops at limit plus one, exact-limit discovery is sorted,
  no manifest opens before the full root scan succeeds, overflow clears the
  Loader-owned snapshot, and no lifecycle or HTTP behavior changed.

- [ ] **Step 2: Re-run focused validation after review fixes**

  Run `.\venv\Scripts\python.exe -m unittest tests.test_plugin_sdk tests.test_plugin_sdk_extended tests.test_plugin_sdk_extended_v2 tests.test_plugin_installation`,
  `.\venv\Scripts\python.exe -m ruff check src/core/kernel/plugin_sdk.py tests/test_plugin_sdk.py`,
  and `.\venv\Scripts\python.exe -m compileall -q src/core/kernel/plugin_sdk.py tests/test_plugin_sdk.py`.
  All commands must exit zero.

### Task 4: Run full Python verification

**Files:**
- Verify: `src/`, `tests/`, and `scripts/`

**Interfaces:**
- Produces: fresh aggregate, discovery, lint, and compile evidence.

- [ ] **Step 1: Run Python validation**

  Run `.\venv\Scripts\python.exe tests/run_all.py`,
  `.\venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"`,
  `.\venv\Scripts\python.exe -m compileall -q src tests scripts`, and
  `.\venv\Scripts\python.exe -m ruff check src tests scripts`. All commands
  must exit zero, with only the two documented skips in the test suites.

### Task 5: Synchronize iteration evidence and validate the ledger

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `AGENTS.md`
- Modify: `docs/DEVELOPMENT_GUIDE.md`
- Modify: `docs/reports/PROJECT_ANALYSIS.md`
- Modify: `docs/reports/README.md`
- Create: `docs/reports/AUDIT_REPORT_207.md`
- Delete: `docs/reports/AUDIT_REPORT_197.md`

**Interfaces:**
- Consumes: fresh validation counts from Task 4.
- Produces: Iteration 207 as the current project evidence with a ten-report window covering 198-207.

- [ ] **Step 1: Update current-state documentation**

  Record Iteration 207, the fixed 8,192-entry boundary, focused and full test
  counts, and the remaining OS-level Plugin isolation work. Remove only
  `docs/reports/AUDIT_REPORT_197.md` from the rolling audit window.

- [ ] **Step 2: Run integration and ledger validation**

  Run `.\venv\Scripts\python.exe scripts/ci_local_integration.py --require-services --timeout 30`,
  `.\venv\Scripts\python.exe -m unittest tests.test_iteration_ledger tests.test_run_all_coverage`,
  and `git diff --check`. All commands must exit zero.

- [ ] **Step 3: Repair and repeat**

  For any failure, isolate whether it is caused by this iteration, apply the
  smallest correction, then rerun the affected command and the final ledger
  check before recording evidence.
