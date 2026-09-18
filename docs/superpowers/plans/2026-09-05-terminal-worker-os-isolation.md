# Fixed Terminal Worker OS Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add parent-owned Windows AppContainer and macOS Seatbelt boundaries to the fixed `TerminalWorker` without changing its terminal protocol or Linux isolation behavior.

**Status:** Implemented and verified through the focused terminal suites. The
remaining release-gate commands, documentation evidence, self-review, and
scoped commit are completed as part of this iteration closeout.

**Architecture:** Extend `TerminalWorker` with explicit isolation controls and reuse the existing `WindowsWorkerContainer`, `MacOSSandbox`, and bounded link-free staging primitives. One lazily-created platform sandbox is retained for the `TerminalWorker` instance, while each command still runs in a short-lived contained child; the parent attaches process-tree containment before resuming a suspended Windows child and retains the sandbox until all descendants are released.

**Tech Stack:** Python 3.10+, `subprocess.Popen`, existing AppContainer and Seatbelt adapters, existing process containment, stdlib `unittest`, aggregate/discovery runners, Ruff.

## Global Constraints

- Windows and macOS automatic isolation applies only to a real, unpatched `subprocess.Popen`.
- Explicit `os_isolation=False` always selects the existing direct launch compatibility path.
- When isolation is selected, setup, staging, launch, containment, resume, and cleanup failures fail closed; there is no ordinary-spawn fallback.
- Linux retains the existing child-applied network namespace and Landlock sequence.
- Trusted source staging uses the shared 8,192-entry link-free `stage_worker_tree()` boundary.
- The child continues to receive only the fixed terminal request schema and bounded response contract.
- The Worker-side `TerminalExecutor` reuses the platform sandbox's external writable root and never owns a nested platform directory.
- Existing user changes in the worktree must remain untouched; only files listed in each task may be changed.

---

### Task 1: Add failing TerminalWorker isolation contract tests

**Files:**
- Modify: `tests/test_terminal_worker.py`

**Interfaces:**
- Consumes: the existing `TerminalWorker`, `TerminalCommand`, `_PendingWorkerProcess`, and `_RecordingContainment` fixtures.
- Produces: regression tests for constructor options, platform selection, staging reuse, launch wiring, containment ordering, and fail-closed setup.

- [x] **Step 1: Add a deterministic fake platform sandbox and process fixture**

Add these test-only helpers beside the existing process fixtures:

```python
class _IsolatedWorkerProcess(_PendingWorkerProcess):
    def __init__(self, stdout: bytes, order: list[str]) -> None:
        super().__init__(stdout)
        self.pid = 4242
        self.order = order

    def resume(self) -> None:
        self.order.append("resume")


class _FakeTerminalSandbox:
    def __init__(self, order: list[str], *, fail_stage: Exception | None = None):
        self.order = order
        self.fail_stage = fail_stage
        self.root = Path(tempfile.mkdtemp(prefix=".test-terminal-os-root-"))
        self.code_root = self.root / "code"
        self.writable_root = self.root / "tmp"
        self.code_root.mkdir()
        self.writable_root.mkdir()
        self.interpreter = Path("C:/Python/python.exe")
        self.stages: list[tuple[Path, str]] = []
        self.spawn_calls: list[dict[str, object]] = []
        self.closed = False
        self._process_factory = lambda: _IsolatedWorkerProcess(
            _worker_payload(command_id="isolated").encode("utf-8"), self.order
        )

    def stage(self, source: Path, name: str) -> Path:
        self.order.append(f"stage:{name}")
        if self.fail_stage is not None:
            raise self.fail_stage
        destination = self.code_root / name
        destination.mkdir()
        self.stages.append((source, name))
        return destination

    def spawn(self, arguments, *, cwd, environment, **keywords):
        self.order.append("spawn")
        self.spawn_calls.append({
            "arguments": list(arguments),
            "cwd": cwd,
            "environment": dict(environment),
            "keywords": dict(keywords),
        })
        return self._process_factory()

    def close(self) -> None:
        self.order.append("sandbox-close")
        self.closed = True
        shutil.rmtree(self.root, ignore_errors=True)

    def close_spawn_handle(self) -> None:
        return None
```

Import `shutil` and `tempfile` if the test module does not already import them. Keep the helper entirely test-local.

- [x] **Step 2: Add the failing selection and override tests**

Add tests with these exact assertions:

```python
def test_explicit_os_isolation_false_overrides_injected_platform_factory(self):
    worker = TerminalWorker(
        os_isolation=False,
        macos_sandbox_factory=lambda: self.fail("factory must not be used"),
    )
    try:
        self.assertFalse(worker._should_use_os_isolation())
    finally:
        worker.close()


def test_injected_macos_factory_enables_isolation_for_a_non_macos_test_host(self):
    factory = lambda: _FakeTerminalSandbox([])
    worker = TerminalWorker(macos_sandbox_factory=factory)
    try:
        self.assertTrue(worker._should_use_os_isolation())
    finally:
        worker.close()
```

- [x] **Step 3: Add the failing macOS launch wiring and staging-reuse test**

Use a factory that returns one fake sandbox, patch `ProcessTreeContainment.attach` to return `_RecordingContainment`, and patch `_bounded_process_communicate` to return a valid bounded response. Assert that two `echo` executions call `stage` exactly once, use `-S -u -m core.kernel.terminal_worker --worker`, use the staged source as `cwd`, pass the fake writable root in `TMPDIR`/`TMP`/`TEMP`, and close the sandbox after `worker.close()`.

The key assertions must be:

```python
self.assertEqual([name for _, name in sandbox.stages], ["src"])
self.assertEqual(len(sandbox.spawn_calls), 2)
launch = sandbox.spawn_calls[0]
self.assertEqual(
    launch["arguments"][1:],
    ["-S", "-u", "-m", "core.kernel.terminal_worker", "--worker"],
)
self.assertEqual(launch["cwd"], sandbox.code_root / "src")
self.assertEqual(launch["environment"]["TMPDIR"], str(sandbox.writable_root))
```

- [x] **Step 4: Add the failing Windows containment-before-resume test**

Inject a fake Windows container, patch the module platform check to `os.name == "nt"`, and assert the event order begins with `stage:src`, `spawn`, `attach`, `resume`. Assert that the container interpreter is the first launch argument and the staged source is the command working directory.

- [x] **Step 5: Add the failing no-fallback setup test**

Configure the injected macOS sandbox to raise `WorkerMacOSSandboxError` from `stage()`, patch the direct module `subprocess.Popen`, execute one command with `os_isolation=True`, and assert a failed `TerminalResult`, `Popen.assert_not_called()`, and `sandbox.closed is True`.

- [x] **Step 6: Run the new tests and verify they fail for the missing behavior**

Run:

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_terminal_worker.TestTerminalWorker.test_explicit_os_isolation_false_overrides_injected_platform_factory tests.test_terminal_worker.TestTerminalWorker.test_injected_macos_factory_enables_isolation_for_a_non_macos_test_host tests.test_terminal_worker.TestTerminalWorker.test_macos_isolated_launch_stages_once_and_uses_the_sandbox_root tests.test_terminal_worker.TestTerminalWorker.test_windows_isolated_launch_attaches_before_resume tests.test_terminal_worker.TestTerminalWorker.test_isolated_setup_failure_never_falls_back_to_direct_spawn -v
```

The initial red phase established the missing constructor and launcher behavior;
the implementation phase now verifies this selection and wiring as green.

### Task 2: Implement parent-owned platform launch for TerminalWorker

**Files:**
- Modify: `src/core/kernel/terminal_worker.py`

**Interfaces:**
- Consumes: `WindowsWorkerContainer`, `MacOSSandbox`, `WorkerContainerError`, `WorkerMacOSSandboxError`, existing `ProcessTreeContainment`, and `stage()`/`spawn()` interfaces.
- Produces: `TerminalWorker.__init__(..., os_isolation=None, container_factory=None, macos_sandbox_factory=None)`, `_should_use_os_isolation()`, and a contained launch path used only by `_execute_reserved()`.

- [x] **Step 1: Add platform imports, constants, and constructor state**

Add:

```python
from .worker_macos_sandbox import MacOSSandbox, WorkerMacOSSandboxError
from .worker_windows_container import WindowsWorkerContainer, WorkerContainerError

_REAL_SUBPROCESS_POPEN = subprocess.Popen
_WORKER_SOURCE_STAGE = "src"
_WINDOWS_PLATFORM = "nt"
```

Change the constructor to keyword-only options:

```python
def __init__(
    self,
    max_output_size: int = 10000,
    *,
    os_isolation: bool | None = None,
    container_factory: Callable[[], WindowsWorkerContainer] | None = None,
    macos_sandbox_factory: Callable[[], MacOSSandbox] | None = None,
):
```

Store the options and initialize:

```python
self._os_isolation = os_isolation
self._container_factory = container_factory
self._macos_sandbox_factory = macos_sandbox_factory
self._os_sandbox: WindowsWorkerContainer | MacOSSandbox | None = None
self._staged_source: Path | None = None
```

Import `Callable` from `typing`.

- [x] **Step 2: Add selection and lazy sandbox creation helpers**

Implement:

```python
def _should_use_os_isolation(self) -> bool:
    if self._os_isolation is not None:
        return bool(self._os_isolation)
    if self._container_factory is not None or self._macos_sandbox_factory is not None:
        return True
    return (
        subprocess.Popen is _REAL_SUBPROCESS_POPEN
        and (os.name == _WINDOWS_PLATFORM or sys.platform == "darwin")
    )


def _ensure_os_sandbox(self) -> tuple[WindowsWorkerContainer | MacOSSandbox, Path]:
    if self._os_sandbox is not None and self._staged_source is not None:
        return self._os_sandbox, self._staged_source
    if self._macos_sandbox_factory is not None or sys.platform == "darwin":
        factory = (
            MacOSSandbox.create
            if self._macos_sandbox_factory is None
            else self._macos_sandbox_factory
        )
    elif self._container_factory is not None or os.name == _WINDOWS_PLATFORM:
        factory = (
            WindowsWorkerContainer.create
            if self._container_factory is None
            else self._container_factory
        )
    else:
        raise RuntimeError("Worker OS isolation is unavailable on this platform")
    sandbox = factory()
    try:
        staged_source = sandbox.stage(WORKER_MODULE_ROOT, _WORKER_SOURCE_STAGE)
    except Exception:
        try:
            sandbox.close()
        finally:
            raise
    self._os_sandbox = sandbox
    self._staged_source = Path(staged_source)
    return sandbox, self._staged_source
```

Use the existing platform exception types in the final implementation where possible; the cleanup `finally` must preserve the original setup exception.

- [x] **Step 3: Add the contained spawn helper**

Implement `_spawn_isolated()` with this behavior:

```python
def _spawn_isolated(self) -> tuple[subprocess.Popen, bool]:
    sandbox, staged_source = self._ensure_os_sandbox()
    if isinstance(sandbox, WindowsWorkerContainer):
        interpreter = sandbox.interpreter
    else:
        interpreter = Path(sys.executable)
    process = sandbox.spawn(
        [
            str(interpreter),
            "-S",
            "-u",
            "-m",
            "core.kernel.terminal_worker",
            WORKER_FLAG,
        ],
        cwd=staged_source,
        environment=_worker_environment(sandbox.writable_root, staged_source),
        **process_group_popen_kwargs(),
    )
    return process, isinstance(sandbox, WindowsWorkerContainer)
```

Update `_worker_environment()` to accept an optional staged module root and use it for `PYTHONPATH` while keeping its existing default for direct Linux launches:

```python
def _worker_environment(
    sandbox_dir: Path,
    module_root: Path = WORKER_MODULE_ROOT,
) -> dict[str, str]:
```

The helper must continue preserving only the existing allowlisted environment keys.

- [x] **Step 4: Route `_execute_reserved()` through the selected launcher**

At the start of `_execute_reserved()`, choose:

```python
if self._should_use_os_isolation():
    process, suspended = self._spawn_isolated()
else:
    process = subprocess.Popen(...existing direct arguments...)
    suspended = False
```

Keep the existing direct launch arguments and bounded communication unchanged. After `ProcessTreeContainment.attach(process)` succeeds and the containment is remembered, resume only a suspended platform child:

```python
if suspended:
    resume = getattr(process, "resume", None)
    if not callable(resume):
        raise RuntimeError("contained Worker cannot resume")
    resume()
```

This ordering must remain `spawn → attach → remember → resume → request`.

- [x] **Step 5: Convert platform setup errors into the existing failure result**

Extend the `_execute_reserved()` launch exception handling to catch
`WorkerContainerError`, `WorkerMacOSSandboxError`, `ProcessContainmentError`,
`OSError`, `RuntimeError`, and `ValueError` as appropriate. Any error before a
contained process is fully owned must close the platform sandbox. Do not invoke
the direct path after an isolated setup failure.

- [x] **Step 6: Make sandbox cleanup retry-safe**

Add:

```python
def _cleanup_os_sandbox(self) -> bool:
    sandbox = self._os_sandbox
    if sandbox is None:
        return True
    try:
        sandbox.close()
    except (OSError, WorkerContainerError, WorkerMacOSSandboxError):
        return False
    self._os_sandbox = None
    self._staged_source = None
    return True
```

In `close()`, release all owned containments first; if release fails, retain the
sandbox and raise the existing containment error. If sandbox cleanup fails,
retain it and raise `RuntimeError("Worker OS sandbox could not be released")`.
Only after both platform cleanup and the existing `TemporaryDirectory.cleanup()`
succeed may the instance set `_closed = True` and `sandbox_dir = None`.

- [x] **Step 7: Run the focused tests and verify green**

Run:

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_terminal_worker -v
```

Expected: all existing TerminalWorker tests and the new platform-boundary tests pass.

### Task 3: Refactor and review the implementation without changing behavior

**Files:**
- Modify: `src/core/kernel/terminal_worker.py`
- Modify: `tests/test_terminal_worker.py`

**Interfaces:**
- Consumes: the green Task 2 implementation and tests.
- Produces: focused helper names, no duplicated launch wiring, and explicit tests for unsupported explicit isolation.

- [x] **Step 1: Add the unsupported-platform failure regression**

With `os_isolation=True`, no factory, and patched `os.name="posix"`, `sys.platform="freebsd"`, assert that execution returns a failed result containing `isolation` and that direct `subprocess.Popen` is not called.

- [x] **Step 2: Add the cleanup retry regression**

Use a fake sandbox whose first `close()` raises `WorkerContainerError` and whose second succeeds. Assert the first `worker.close()` leaves `_closed` false and the second releases the sandbox and parent temporary root.

- [x] **Step 3: Run focused tests and Ruff**

Run:

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_terminal_worker -v
.\venv\Scripts\python.exe -m ruff check src/core/kernel/terminal_worker.py tests/test_terminal_worker.py
```

Expected: all focused tests pass and Ruff reports zero findings.

### Task 4: Update iteration evidence and project guidance

**Files:**
- Create: `docs/reports/AUDIT_REPORT_242.md`
- Modify: `CHANGELOG.md`
- Modify: `AGENTS.md`
- Modify: `README.md`
- Modify: `docs/DEVELOPMENT_GUIDE.md`
- Modify: `docs/reports/PROJECT_ANALYSIS.md`
- Modify: `docs/reports/README.md`

**Interfaces:**
- Consumes: the final implementation and fresh test output.
- Produces: honest Iteration 242 evidence that distinguishes Windows enforcement, macOS contract-only evidence on this host, and Linux unchanged behavior.

- [x] **Step 1: Add the Iteration 242 changelog entry at the top**

Document the parent-owned fixed Terminal Worker boundary, staging reuse, containment-before-resume ordering, no-fallback rule, explicit compatibility switch, and the fact that macOS kernel enforcement remains unverified on Windows.

- [x] **Step 2: Update current-state guidance**

Replace statements that Windows/macOS fixed Terminal Worker isolation is absent with the exact status: Windows uses production AppContainer, macOS uses production Seatbelt when available, Linux retains namespace/Landlock, and platform-specific kernel evidence must not be inferred from injected contract tests.

- [x] **Step 3: Write the audit report from fresh command output**

Include a requirement matrix for selection, staging, writable-root, process ownership, fail-closed setup, and protocol preservation. Include exact totals from the final aggregate/discovery commands rather than copying historical counts.

- [x] **Step 4: Run documentation and diff checks**

Run:

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_iteration_ledger tests.test_readme tests.test_docs_setup -v
git diff --check
```

Expected: all targeted documentation tests pass and `git diff --check` exits 0.

### Task 5: Full verification and isolated commit review

**Files:**
- Verify: all changed files from Tasks 1–4

**Interfaces:**
- Consumes: the complete implementation, tests, and documentation.
- Produces: fresh evidence for the final self-review and a scoped commit containing only this iteration's files.

- [x] **Step 1: Run the aggregate Python suite**

```powershell
.\venv\Scripts\python.exe tests/run_all.py --timeout 1800 --json-report .test-i242-aggregate.json
```

Expected: exit 0, zero failures, and the report is ignored/removed according to the existing `.gitignore` policy.

- [x] **Step 2: Run full discovery and static checks**

```powershell
.\venv\Scripts\python.exe scripts/discover_tests.py --timeout 1800 --json-report .test-i242-discovery.json
.\venv\Scripts\python.exe -m compileall -q src tests scripts
.\venv\Scripts\python.exe -m ruff check src tests scripts
```

Expected: discovery exits 0, compileall is silent, and Ruff reports `All checks passed!`.

- [x] **Step 3: Run frontend verification because project release gates require it**

```powershell
Set-Location frontend
npm test -- --run
npm run typecheck
npm run build
npm run test:e2e
Set-Location ..
```

Expected: Vitest, typecheck, build, and the existing Playwright pass/conditional-skip contract remain green.

- [x] **Step 4: Perform the final self-review before committing**

Inspect `git diff --stat`, `git diff -- src/core/kernel/terminal_worker.py tests/test_terminal_worker.py`, and all documentation diffs. Confirm that no direct fallback occurs after selected isolation setup fails, the staged path never replaces the parent Broker/API path (TerminalWorker has no Broker), containment precedes Windows resume, cleanup retains resources after an unconfirmed descendant, and no unrelated user changes are included.

- [x] **Step 5: Commit only the Iteration 242 files**

```powershell
git add src/core/kernel/terminal_worker.py tests/test_terminal_worker.py CHANGELOG.md AGENTS.md README.md docs/DEVELOPMENT_GUIDE.md docs/reports/PROJECT_ANALYSIS.md docs/reports/README.md docs/reports/AUDIT_REPORT_242.md docs/superpowers/specs/2026-09-05-terminal-worker-os-isolation-design.md docs/superpowers/plans/2026-09-05-terminal-worker-os-isolation.md
git commit -m "feat: isolate fixed terminal worker on windows and macos"
```

Expected: the commit contains only the listed iteration files; existing unrelated modifications remain unstaged and untouched.
