# macOS Seatbelt Enforcement Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a platform-gated macOS enforcement probe and CI job proving that the existing parent-owned Seatbelt boundary denies ungranted file reads and loopback network access while allowing the Worker-owned writable root.

**Architecture:** Keep `MacOSSandbox` and its `(deny default)` profile unchanged. Add an independent unittest that writes a small probe, stages it through `MacOSSandbox.stage()`, launches it through `MacOSSandbox.spawn()`, and checks three JSON outcomes. Run the probe only on macOS with `sandbox-exec`; Windows/Linux explicitly skip it and retain contract coverage.

**Tech Stack:** Python 3.10+, `unittest`, `subprocess.Popen`, `socket`, macOS `sandbox-exec`, GitHub Actions, the existing hash-locked dependency installation.

## Global Constraints

- Do not broaden or replace the production macOS policy.
- The enforcement test is skipped unless `sys.platform == "darwin"` and `shutil.which("sandbox-exec")` is available.
- The probe uses a parent-bound loopback listener, a file outside all granted roots, and `MacOSSandbox.writable_root`; an unused port is not valid network evidence.
- Child startup uses a minimal environment, `-S -u`, no shell text, and `communicate(timeout=5)`.
- Preserve every pre-existing working-tree change, staged deletion, and `.auto-memory` file.

---

### Task 1: Add the real-enforcement probe test

**Files:**
- Create: `tests/test_macos_sandbox_enforcement.py`

**Interfaces:**
- Consumes: `MacOSSandbox.create()`, `MacOSSandbox.stage()`, `MacOSSandbox.spawn()`, `MacOSSandbox.writable_root`, and `default_runtime_read_paths()`.
- Produces: `TestMacOSSandboxEnforcement.test_seatbelt_denies_ungranted_read_and_loopback_but_allows_worker_root`.

- [x] **Step 1: Write the failing test**

Create the test with this exact child probe source and harness shape:

```python
@unittest.skipUnless(
    sys.platform == "darwin" and shutil.which("sandbox-exec"),
    "real Seatbelt enforcement requires macOS sandbox-exec",
)
class TestMacOSSandboxEnforcement(unittest.TestCase):
    def test_seatbelt_denies_ungranted_read_and_loopback_but_allows_worker_root(self):
        probe_source = (
            "import json, os, socket\n"
            "from pathlib import Path\n"
            "result = {}\n"
            "try:\n"
            "    Path(os.environ[\"PROBE_OUTSIDE\"]).read_text(encoding=\"utf-8\")\n"
            "except OSError:\n"
            "    result[\"outside_read\"] = \"denied\"\n"
            "else:\n"
            "    result[\"outside_read\"] = \"allowed\"\n"
            "try:\n"
            "    with socket.create_connection((\"127.0.0.1\", int(os.environ[\"PROBE_PORT\"])), timeout=1):\n"
            "        pass\n"
            "except OSError:\n"
            "    result[\"loopback\"] = \"denied\"\n"
            "else:\n"
            "    result[\"loopback\"] = \"allowed\"\n"
            "try:\n"
            "    Path(os.environ[\"TMPDIR\"], \"probe-write.txt\").write_text(\"ok\", encoding=\"utf-8\")\n"
            "except OSError:\n"
            "    result[\"write\"] = \"denied\"\n"
            "else:\n"
            "    result[\"write\"] = \"allowed\"\n"
            "print(json.dumps(result, sort_keys=True), flush=True)\n"
        )
        with tempfile.TemporaryDirectory(prefix=".test-macos-enforcement-") as temporary:
            root = Path(temporary)
            outside = root / "outside.txt"
            outside.write_text("must remain unreadable", encoding="utf-8")
            source = root / "probe-source"
            source.mkdir()
            (source / "probe.py").write_text(probe_source, encoding="utf-8")
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            try:
                try:
                    runtime_read_paths = default_runtime_read_paths()
                except WorkerWindowsIsolationError as error:
                    self.skipTest(f"Python runtime paths are unavailable: {error}")
                sandbox = MacOSSandbox.create(runtime_read_paths=runtime_read_paths)
                try:
                    staged = sandbox.stage(source, "probe")
                    process = sandbox.spawn(
                        [str(sys.executable), "-S", "-u", "probe.py"],
                        cwd=staged,
                        environment={
                            "PATH": os.environ.get("PATH", os.defpath),
                            "PYTHONIOENCODING": "utf-8",
                            "PYTHONUNBUFFERED": "1",
                            "PYTHONNOUSERSITE": "1",
                            "TMPDIR": str(sandbox.writable_root),
                            "PROBE_OUTSIDE": str(outside),
                            "PROBE_PORT": str(listener.getsockname()[1]),
                        },
                    )
                    try:
                        stdout, stderr = process.communicate(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.communicate()
                        self.fail("macOS Seatbelt probe exceeded its 5-second deadline")
                finally:
                    sandbox.close()
            finally:
                listener.close()
        self.assertEqual(process.returncode, 0, stderr.decode("utf-8", errors="replace"))
        self.assertEqual(
            json.loads(stdout.decode("utf-8")),
            {"outside_read": "denied", "loopback": "denied", "write": "allowed"},
        )
```

Import `json`, `os`, `shutil`, `socket`, `subprocess`, `sys`, `tempfile`, `unittest`, `Path`, `MacOSSandbox`, `WorkerWindowsIsolationError`, and `default_runtime_read_paths`. Catch only `OSError` inside the child around the restricted operations. The listener must remain open while the child runs, so a non-sandboxed connection becomes `"allowed"` and fails the assertion. A runtime-path lookup failure is the only setup condition converted to `SkipTest`; staging, launch, non-zero exit, malformed JSON, timeout, and wrong access results fail.

- [x] **Step 2: Run the new test and verify the platform gate**

Run:

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_macos_sandbox_enforcement -v
```

Expected on the current Windows host: one explicit skip for the macOS enforcement test.

- [x] **Step 3: Run focused macOS contract coverage**

Run:

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_worker_macos_sandbox tests.test_macos_sandbox_enforcement -v
```

Expected: existing contract tests pass and the enforcement test skips on Windows.

### Task 2: Add an independent macOS CI job

**Files:**
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: the repository checkout, Python 3.11, `requirements.lock`, and the two macOS sandbox test modules.
- Produces: a `macos-sandbox` job on `macos-latest` independent of Ollama, frontend services, and other jobs.

- [x] **Step 1: Append the job without changing existing jobs**

Add this YAML under `jobs:` and preserve the current unrelated workflow diff:

```yaml
  macos-sandbox:
    runs-on: macos-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: python -m pip install --require-hashes -r requirements.lock
      - run: python -m pip install --no-deps --no-build-isolation -e .
      - run: python -m unittest tests.test_worker_macos_sandbox tests.test_macos_sandbox_enforcement -v
```

- [x] **Step 2: Validate the workflow contract**

Run `git diff --check -- .github/workflows/ci.yml` and ` .\venv\Scripts\python.exe -m unittest tests.test_ci_workflow -v` (without the leading space before the executable). Expected: no whitespace errors and existing workflow tests pass.

### Task 3: Record Iteration 243 evidence

**Files:**
- Modify: `AGENTS.md`
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/DEVELOPMENT_GUIDE.md`
- Modify: `docs/reports/PROJECT_ANALYSIS.md`
- Modify: `docs/reports/README.md`
- Create: `docs/reports/AUDIT_REPORT_243.md`

**Interfaces:**
- Consumes: fresh focused, aggregate, discovery, lint, compile, and workflow verification output.
- Produces: current guidance and an audit report distinguishing Windows-host skips from macOS kernel evidence.

- [x] **Step 1: Update current summaries and navigation**

Record that Iteration 243 adds the real `sandbox-exec` probe and dedicated macOS job; the current Windows host explicitly skips the probe, and only a macOS runner can establish the three enforcement outcomes. Preserve the production fail-closed and `sandbox-exec` deprecation statements.

- [x] **Step 2: Write `AUDIT_REPORT_243.md`**

Include `Iteration: #243`, `Date: 2026-09-05`, `Status: Complete`, scope, requirement/evidence matrix, self-review, exact verification results, changed files, and residual risks. Do not describe the Windows skip as kernel enforcement.

- [x] **Step 3: Run documentation regressions**

Run:

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_readme tests.test_docs_setup tests.test_iteration_ledger -v
```

### Task 4: Full verification and isolated delivery

**Files:**
- Inspect only: Iteration 243 diffs and existing working-tree status

- [x] **Step 1: Run focused and static gates**

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_worker_macos_sandbox tests.test_macos_sandbox_enforcement tests.test_ci_workflow tests.test_readme tests.test_docs_setup tests.test_iteration_ledger
.\venv\Scripts\python.exe -m compileall -q src tests scripts
.\venv\Scripts\python.exe -m ruff check src tests scripts
git diff --check
```

- [x] **Step 2: Run aggregate and discovery**

```powershell
.\venv\Scripts\python.exe tests/run_all.py --timeout 1800 --json-report .test-i243-aggregate.json
.\venv\Scripts\python.exe scripts/discover_tests.py --timeout 1800 --json-report .test-i243-discovery.json
```

The aggregate count is expected to remain unchanged because `tests/run_all.py` already contains unrelated user modifications and is intentionally not touched; discovery must include the new module and its Windows skip. The iteration-243 documentation and plan scope passes `git diff --check`; the full working-tree check also sees pre-existing CRLF-only whitespace in `.github/workflows/ci.yml`, which is preserved as user work.

- [x] **Step 3: Review and commit only Iteration 243 files**

Run `git status --short`, `git diff --stat`, and `git diff --check`; verify the probe uses a real listener, bounded timeout, and the existing sandbox APIs, and that no pre-existing path is staged. Commit the test, workflow, guidance, audit report, plan, and design files in separate focused commits while leaving all unrelated changes in place.
