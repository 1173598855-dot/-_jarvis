# Windows Plugin Worker AppContainer Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete and verify the Windows AppContainer launch path for production Plugin Workers, including failure cleanup and synchronized Iteration 240 evidence.

**Architecture:** Keep AppContainer profile/SID/ACL ownership in `worker_windows_isolation.py`, container staging and `CreateProcessW` in `worker_windows_container.py`, and platform selection/lifecycle ordering in `SubprocessPluginRuntime`. Preserve the existing parent Broker and process-tree containment contracts; direct/POSIX spawning remains available only when explicitly selected or when the real Windows boundary is not applicable.

**Tech Stack:** Python 3.10+, Windows `ctypes`/`CreateProcessW`, `icacls`, `subprocess.Popen` compatibility, stdlib `unittest`, existing aggregate/discovery runners.

## Global Constraints

- Preserve unrelated user changes already present in the working tree, especially Iteration 225-239 implementation and evidence files.
- Never fall back from a Windows container setup failure to an ordinary Worker process.
- Keep the AppContainer capability set empty; grant only staged code read/execute and one Worker-owned writable root.
- Keep the parent Broker bound to the validated real plugin root and keep the child on a staged plugin root.
- Do not delete or rewrite `.auto-memory` or unrelated ignored `.test-*` artifacts.
- Do not stage or commit unrelated pre-existing working-tree changes; inspect focused diffs before any commit decision.

---

### Task 1: Lock the SID-conversion failure cleanup contract

**Files:**
- Modify: `tests/test_worker_windows_isolation.py`
- Modify: `src/core/kernel/worker_windows_isolation.py`

**Interfaces:**
- Consumes: `prepare_windows_worker_isolation(writable_root, platform_name, api_factory, grant)`.
- Produces: a failure path that releases the SID returned by `create_or_adopt()` and deletes the profile when that call created it, even if `sid_text()` raises.

- [ ] **Step 1: Add the failing regression test**

Extend `TestWindowsIsolationContract.test_sid_failure_fails_closed` so the fake API is retained and the assertions prove both cleanup actions:

```python
    def test_sid_failure_releases_sid_and_created_profile(self) -> None:
        api = _FakeApi(created=True, fail_at="sid")
        with self.assertRaises(WorkerWindowsIsolationError):
            prepare_windows_worker_isolation(
                Path(tempfile.gettempdir()),
                profile_name="jarvis.sid-failure.ac",
                platform_name="win32",
                api_factory=lambda: api,
            )
        self.assertTrue(api.released)
        self.assertEqual(api.deleted, ["jarvis.sid-failure.ac"])
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_worker_windows_isolation.TestWindowsIsolationContract.test_sid_failure_releases_sid_and_created_profile -v
```

Expected: FAIL because the current exception path has no identity object yet and therefore does not release the returned SID or delete the newly created profile.

- [ ] **Step 3: Implement the minimal cleanup**

In `prepare_windows_worker_isolation`, retain the `sid` and `created` values in the `try` scope, and when `api.sid_text(sid)` raises, call `api.release_sid(sid)` and call `api.delete_profile(profile_name)` only when `created` is true before re-raising the original exception. Keep the existing identity-based cleanup for grant failures unchanged.

- [ ] **Step 4: Run the focused test and the module**

Run:

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_worker_windows_isolation.TestWindowsIsolationContract.test_sid_failure_releases_sid_and_created_profile -v
.\venv\Scripts\python.exe -m unittest tests.test_worker_windows_isolation -v
```

Expected: the new test and all Windows isolation contract/real-enforcement tests pass, with the real-enforcement class skipped only when the host is not Windows.

### Task 2: Complete deterministic runtime selection and quality gates

**Files:**
- Modify: `tests/test_subprocess_plugin_runtime.py`
- Modify: `tests/run_all.py`
- Modify: `tests/test_worker_windows_container.py`
- Modify: `src/adapters/subprocess_plugin_runtime.py` only if a test identifies a behavior defect

**Interfaces:**
- Consumes: `SubprocessPluginRuntime._should_use_os_isolation()`, `_spawn_contained()`, `_spawn_direct()`, `WindowsWorkerContainer.spawn()` and the `os_isolation`/`container_factory` constructor options.
- Produces: deterministic regression coverage showing explicit bypass wins, an injected factory enables the branch, and the existing runtime keeps ownership until contained cleanup is confirmed.

- [ ] **Step 1: Add selection tests before changing production code**

Add focused tests to `TestSubprocessPluginRuntime` using the existing `_runtime_for` helper:

```python
    def test_explicit_os_isolation_false_overrides_container_factory(self) -> None:
        runtime = self._runtime_for("def activate(api):\n    pass\n")
        runtime._container_factory = lambda: object()
        runtime._os_isolation = False
        self.assertFalse(runtime._should_use_os_isolation())

    def test_container_factory_enables_isolation_for_non_windows_test_host(self) -> None:
        runtime = self._runtime_for("def activate(api):\n    pass\n")
        runtime._container_factory = lambda: object()
        runtime._os_isolation = None
        self.assertTrue(runtime._should_use_os_isolation())
```

- [ ] **Step 2: Run the selection tests**

Run:

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_subprocess_plugin_runtime.TestSubprocessPluginRuntime.test_explicit_os_isolation_false_overrides_container_factory tests.test_subprocess_plugin_runtime.TestSubprocessPluginRuntime.test_container_factory_enables_isolation_for_non_windows_test_host -v
```

Expected: PASS against the current implementation; this records the already-delivered selection contract and detects future accidental fallback changes.

- [ ] **Step 3: Repair only quality failures**

Order the imports reported by Ruff in `tests/run_all.py` and `tests/test_worker_windows_container.py`. Do not use broad formatter rewrites or alter unrelated test registration.

- [ ] **Step 4: Run focused runtime and aggregate coverage**

Run:

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_subprocess_plugin_runtime tests.test_worker_windows_container tests.test_worker_windows_isolation tests.test_plugin_sdk
.\venv\Scripts\python.exe -m ruff check src tests scripts
.\venv\Scripts\python.exe -m compileall -q src tests scripts
```

Expected: all focused tests pass and Ruff reports zero findings.

### Task 3: Synchronize Iteration 240 evidence and perform the full self-review

**Files:**
- Modify: `AGENTS.md`
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/DEVELOPMENT_GUIDE.md`
- Modify: `docs/reports/PROJECT_ANALYSIS.md`
- Modify: `docs/reports/README.md`
- Create: `docs/reports/AUDIT_REPORT_240.md`
- Modify: `tests/test_iteration_ledger.py` only if current evidence format requires no production behavior change

**Interfaces:**
- Consumes: fresh aggregate/discovery/frontend verification totals and the exact focused diff.
- Produces: Iteration 240 documentation that states Windows production AppContainer integration honestly, preserves Linux/macOS residual boundaries, and matches the current test totals.

- [ ] **Step 1: Run the final backend and frontend gates**

Run:

```powershell
.\venv\Scripts\python.exe tests\run_all.py --timeout 1800 --json-report .test-i240-runall.json
.\venv\Scripts\python.exe scripts\discover_tests.py --timeout 1800
.\venv\Scripts\python.exe -m ruff check src tests scripts
.\venv\Scripts\python.exe -m compileall -q src tests scripts
Push-Location frontend
npm test -- --run
npm run typecheck
npm run build
npm run test:e2e
Pop-Location
git diff --check
```

Expected: all required commands exit 0; platform-conditional tests are counted as skips, not passes; the aggregate and discovery totals are copied from the current run rather than historical reports.

- [ ] **Step 2: Review the requirement matrix**

Check each item explicitly: parent-created identity, empty capability set, read-only staged code, exactly one writable root, suspended launch ordering, no direct fallback, profile/SID failure cleanup, Broker real-root ownership, confirmed process-tree cleanup, truthful platform skips, and preserved public protocol behavior.

- [ ] **Step 3: Update evidence only after verification**

Write `AUDIT_REPORT_240.md` with scope, changes, self-review, exact commands/results and residual risks. Update the current iteration pointers and counts in the six maintained project documents. Keep old reports intact unless the rolling-window policy and the exact user-owned report state permit removing the oldest entry; do not delete an untracked report merely to make the count look tidy.

- [ ] **Step 4: Inspect the final focused diff and resource state**

Run:

```powershell
git status --short
git diff --stat -- src tests docs/reports/AUDIT_REPORT_240.md docs/superpowers
Get-ChildItem -Force -Filter '.auto-memory*'
```

Expected: only the SID cleanup, regression coverage, lint corrections, design/plan and Iteration 240 evidence are attributable to this continuation; all pre-existing user changes remain present and `.auto-memory` is untouched.

