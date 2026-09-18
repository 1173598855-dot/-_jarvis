# Linux Plugin Runtime Enforcement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove on a real Linux kernel that the production `SubprocessPluginRuntime` lifecycle applies its namespace and Landlock boundary before Plugin code executes, preserves Broker communication and reclaims its owned process and temporary root.

**Architecture:** Add one opt-in unittest that starts a small probe driver under an unprivileged identity. The driver uses the real Runtime, Worker, Broker and EventBus; a purpose-built Plugin reports attempted outside file access, loopback access and Worker-root writes through `event.emit`. Register the skipped-by-default test in the aggregate suite and run it explicitly in the existing Ubuntu 22.04 sandbox job.

**Tech Stack:** Python 3.11 standard library, `unittest`, existing J.A.R.V.I.S. Plugin Worker protocol and Broker, GitHub Actions, WSL2 Ubuntu 24.04 for local kernel evidence.

## Global Constraints

- Gate execution with `JARVIS_RUN_LINUX_PLUGIN_RUNTIME_ENFORCEMENT=1` and skip honestly on non-Linux hosts.
- Do not change Worker, Broker, Plugin, lifecycle or capability production contracts.
- Do not introduce dependencies, fake denials, injected isolation APIs or a test-only production hook.
- Use fixed subprocess and lifecycle deadlines; bound diagnostics shown by the outer test.
- Preserve all unrelated dirty-worktree changes and do not create a broad commit from the shared worktree.
- Treat only a non-skipped Linux run as kernel-enforcement evidence.

---

### Task 1: Add The Production Runtime Probe And Failing Wiring Contracts

**Files:**
- Create: `tests/test_linux_plugin_runtime_enforcement.py`
- Modify: `tests/test_run_all_coverage.py`
- Modify: `tests/test_ci_workflow.py`

**Interfaces:**
- Consumes: `SubprocessPluginRuntime.start()`, `invoke(LifecycleAction)`, `close()`, `PluginRuntimeSnapshot`, `PluginLifecycleResult`, `PluginBroker.register_event_emit_handler()`, and `EventBus.get_history(event_type, limit)`.
- Produces: `TestLinuxPluginRuntimeEnforcement`, opt-in environment variable `JARVIS_RUN_LINUX_PLUGIN_RUNTIME_ENFORCEMENT`, and static expectations for aggregate/CI registration.

- [x] **Step 1: Write the opt-in enforcement test**

Create a `unittest` module with this externally visible contract:

```python
RUN_REAL_ENFORCEMENT = (
    sys.platform.startswith("linux")
    and os.environ.get("JARVIS_RUN_LINUX_PLUGIN_RUNTIME_ENFORCEMENT") == "1"
)


@unittest.skipUnless(
    RUN_REAL_ENFORCEMENT,
    "requires an explicit real Linux Plugin Runtime isolation run",
)
class TestLinuxPluginRuntimeEnforcement(unittest.TestCase):
    def test_production_runtime_enforces_worker_boundary(self) -> None:
        result = self._run_probe_driver_as_unprivileged_identity()
        self.assertEqual(result["baseline"]["outside_read"], "allowed")
        self.assertEqual(result["baseline"]["outside_write"], "allowed")
        self.assertEqual(result["baseline"]["loopback"], "allowed")
        self.assertNotEqual(result["driver_pid"], result["worker_pid"])
        self.assertEqual(result["lifecycle"], ["loaded", "enabled"])
        self.assertEqual(result["restricted"]["outside_read"], "denied")
        self.assertEqual(result["restricted"]["outside_write"], "denied")
        self.assertEqual(result["restricted"]["loopback"], "denied")
        self.assertEqual(result["restricted"]["worker_write"], "allowed")
        self.assertTrue(result["worker_exists_before_close"])
        self.assertTrue(result["termination_confirmed"])
        self.assertTrue(result["worker_root_reclaimed"])
```

`_run_probe_driver_as_unprivileged_identity()` is a test-only helper in the
same module. It owns the temporary tree and listener, launches the complete
driver source below with `subprocess.Popen`, applies `os.setgroups([])`,
`os.setgid(12345)` and `os.setuid(12345)` from `preexec_fn` when the test is
root, concurrently caps stdout and stderr at 8 KiB per stream, enforces a
20-second deadline, terminates both independent process groups on failure,
requires exit code zero, and parses the driver's single UTF-8 JSON line. The
helper is not imported by production code.

The generated Plugin must emit `plugin.linux_runtime_probe` with exactly these
semantic fields:

```python
{
    "outside_read": "denied",
    "outside_write": "denied",
    "plugin_root_write": "denied",
    "loopback": "denied",
    "worker_write": "allowed",
    "worker_path": str(worker_path),
}
```

The driver must construct and exercise only existing production objects:

```python
bus = EventBus()
broker = PluginBroker(bus, grants={plugin_root.name: {"event.emit"}})
broker.register_event_emit_handler()
runtime = SubprocessPluginRuntime(
    plugin_root,
    PluginLoadSpec("plugin.py", ("event_bus",), "1.0.0", 1),
    broker,
    timeouts=PluginWorkerTimeouts(
        handshake=5,
        load=5,
        activate=5,
        deactivate=5,
        cleanup=5,
        shutdown=5,
        terminate=1,
        kill=1,
    ),
)
snapshot = runtime.start()
loaded = runtime.invoke(LifecycleAction.LOAD)
activated = runtime.invoke(LifecycleAction.ACTIVATE)
event = bus.get_history("plugin.linux_runtime_probe", limit=1)[0]
worker_path = Path(event.payload["worker_path"])
worker_exists_before_close = worker_path.is_file()
runtime.close()
termination_confirmed = runtime.snapshot.termination_confirmed
worker_root_reclaimed = not worker_path.parent.exists()
bus.destroy()
```

The outer assertion must require an accessible pre-isolation baseline, distinct driver/Worker PIDs, `loaded` then `enabled`, the exact denied/allowed payload, unchanged outside content, a present Worker file before close, confirmed termination and a reclaimed Worker root after close.

- [x] **Step 2: Add aggregate and workflow expectations before wiring them**

Extend `TestRunAllCoverage` with:

```python
def test_aggregate_runner_includes_linux_plugin_runtime_enforcement_guard_once(self):
    case_ids = [
        (case.__module__, case.__name__)
        for case in run_all.AGGREGATE_TEST_CASES
    ]
    self.assertIn(
        (
            "test_linux_plugin_runtime_enforcement",
            "TestLinuxPluginRuntimeEnforcement",
        ),
        case_ids,
    )
    self.assertEqual(len(case_ids), len(set(case_ids)))
```

Extend `TestCiWorkflow.test_linux_sandbox_job_runs_the_opt_in_real_enforcement_probe` with exact assertions for `tests.test_linux_plugin_runtime_enforcement` and `JARVIS_RUN_LINUX_PLUGIN_RUNTIME_ENFORCEMENT: "1"`.

- [x] **Step 3: Run the contracts to verify they fail for missing wiring**

Run:

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_run_all_coverage.TestRunAllCoverage.test_aggregate_runner_includes_linux_plugin_runtime_enforcement_guard_once tests.test_ci_workflow.TestCiWorkflow.test_linux_sandbox_job_runs_the_opt_in_real_enforcement_probe -v
```

Expected: two assertion failures identifying the missing aggregate class and missing CI command/environment variable.

- [x] **Step 4: Verify the new enforcement module skips honestly on Windows**

Run:

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_linux_plugin_runtime_enforcement -v
```

Expected: one skipped test with the explicit real-Linux reason.

### Task 2: Register The Probe And Obtain Real Linux Evidence

**Files:**
- Modify: `tests/run_all.py`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: `TestLinuxPluginRuntimeEnforcement` from Task 1 and the existing `linux-sandbox` job.
- Produces: one aggregate-suite registration and an Ubuntu 22.04 invocation with both Linux enforcement opt-ins enabled.

- [x] **Step 1: Register the unittest in the aggregate suite**

Add this import beside the primitive Linux enforcement import:

```python
from test_linux_plugin_runtime_enforcement import TestLinuxPluginRuntimeEnforcement
```

Add `TestLinuxPluginRuntimeEnforcement` exactly once beside `TestLinuxWorkerIsolationEnforcement` in `AGGREGATE_TEST_CASES`.

- [x] **Step 2: Extend the Linux sandbox CI step**

Change the existing command and environment to:

```yaml
- run: python -m unittest tests.test_worker_network_isolation tests.test_worker_filesystem_isolation tests.test_linux_worker_isolation_enforcement tests.test_linux_plugin_runtime_enforcement -v
  env:
    JARVIS_RUN_LINUX_ISOLATION_ENFORCEMENT: "1"
    JARVIS_RUN_LINUX_PLUGIN_RUNTIME_ENFORCEMENT: "1"
```

- [x] **Step 3: Run the static wiring contracts to verify they pass**

Run the Task 1 Step 3 command again.

Expected: two tests pass.

- [x] **Step 4: Run the real WSL2 production Runtime probe**

Run:

```powershell
wsl.exe -d Ubuntu-24.04 -- bash -lc 'cd /mnt/c/GitHub/贾维斯 && PYTHONPATH=src JARVIS_RUN_LINUX_PLUGIN_RUNTIME_ENFORCEMENT=1 python3 -m unittest tests.test_linux_plugin_runtime_enforcement -v'
```

Expected: one non-skipped passing test proving the real lifecycle and boundary. If it fails, use `systematic-debugging` before any production change, preserve the failure output, identify the earliest violated invariant and add the narrowest regression test before implementing a fix.

- [x] **Step 5: Run the complete Linux sandbox command in WSL2**

Run the same four modules and both environment variables used by CI.

Expected: all contract tests plus both real probes pass without skips.

### Task 3: Self-Review, Full Verification And Iteration Evidence

**Files:**
- Modify: `AGENTS.md`
- Modify: `CHANGELOG.md`
- Modify: `README.md`
- Modify: `docs/DEVELOPMENT_GUIDE.md`
- Modify: `docs/reports/PROJECT_ANALYSIS.md`
- Modify: `docs/reports/README.md`
- Create: `docs/reports/AUDIT_REPORT_246.md`

**Interfaces:**
- Consumes: exact results from the verification commands below.
- Produces: Iteration 246's current-state description, report navigation entry and reproducible evidence without changing historical reports.

- [x] **Step 1: Review the implementation diff**

Run:

```powershell
git diff -- tests/test_linux_plugin_runtime_enforcement.py tests/test_run_all_coverage.py tests/test_ci_workflow.py tests/run_all.py .github/workflows/ci.yml
git diff --check -- tests/test_linux_plugin_runtime_enforcement.py tests/test_run_all_coverage.py tests/test_ci_workflow.py tests/run_all.py .github/workflows/ci.yml
```

Check that the test uses a real Runtime and Worker, baseline checks precede isolation, the Plugin receives no undeclared Broker capability, cleanup occurs on every path, and Windows contributes only a skip.

- [x] **Step 2: Run focused quality and Python verification**

Run:

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_linux_plugin_runtime_enforcement tests.test_run_all_coverage tests.test_ci_workflow -v
.\venv\Scripts\python.exe -m ruff check src tests scripts
.\venv\Scripts\python.exe -m compileall -q src tests scripts
.\venv\Scripts\python.exe tests/run_all.py --timeout 1800 --json-report .test-run-all-246.json
.\venv\Scripts\python.exe scripts/discover_tests.py --timeout 1800 --json-report .test-discover-246.json
```

Expected: focused checks pass with the runtime probe skipped on Windows; Ruff and compileall exit 0; aggregate and discovery report no failures.

- [x] **Step 3: Run unchanged frontend gates**

Run from `frontend/`:

```powershell
npm test -- --run
npm run test:e2e
npm run typecheck
npm run build
```

Expected: Vitest, Playwright, typecheck and production build pass; preserve any declared platform-conditional Playwright skip.

- [x] **Step 4: Record exact Iteration 246 evidence**

Update all listed current-state documents with the measured aggregate/discovery totals, focused Windows skip, WSL2 non-skipped result, Linux CI path and explicit distinction between primitive evidence and production Runtime evidence. Roll report navigation forward to the newest ten reports without deleting unrelated worktree files.

- [x] **Step 5: Run final documentation and worktree checks**

Run:

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_iteration_ledger tests.test_readme tests.test_resume_document tests.test_docs_setup -v
git diff --check
git status --short
```

Expected: documentation contracts pass, the complete dirty worktree has no whitespace errors, and status shows only preserved prior work plus intentional Iteration 246 files.
