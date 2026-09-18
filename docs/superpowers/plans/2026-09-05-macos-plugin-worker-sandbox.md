# macOS Plugin Worker Sandbox Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a fail-closed, parent-owned macOS `sandbox-exec` boundary to production Plugin Worker startup with bounded staging and honest platform evidence.

**Architecture:** Extract the existing bounded Worker-tree staging primitive into a shared kernel helper. Add a macOS sandbox generation that creates a private staging root, constructs a Seatbelt profile, and launches `sandbox-exec`; route `SubprocessPluginRuntime` to it only on real macOS or through an injected factory. Preserve the parent Broker, process containment, cleanup, and direct/POSIX compatibility contracts.

**Tech Stack:** Python 3.10+, macOS `sandbox-exec`, Seatbelt profiles, `subprocess.Popen`, stdlib `unittest`, existing aggregate/discovery runners.

## Global Constraints

- The profile must begin with `(deny default)` and must not grant network access.
- Only staged code/runtime paths may be read and only one Worker-owned root may be written.
- Staging rejects links and enforces the shared 8,192-entry budget before copying.
- Automatic macOS setup failures fail closed; no direct-spawn fallback is allowed.
- The parent Broker remains bound to the validated real Plugin root.
- Do not claim real macOS kernel enforcement from Windows-host contract tests.
- Preserve all unrelated working-tree changes and do not modify `.auto-memory`.

---

### Task 1: Add failing macOS sandbox contract tests

**Files:**
- Create: `tests/test_worker_macos_sandbox.py`
- Modify: `tests/test_subprocess_plugin_runtime.py`

**Interfaces:**
- Consumes: desired `MacOSSandbox`, `macos_sandbox_profile`, and runtime selection interfaces.
- Produces: red tests for profile restrictions, path escaping, staging cleanup, launcher failure, and macOS branch selection.

- [ ] Add tests that import the missing module and assert `(deny default)`, no network allowance, exact write-root allowance, escaped paths, invalid path rejection, and bounded link-free staging.
- [ ] Add runtime selection tests proving an injected macOS factory selects the branch and explicit `os_isolation=False` wins.
- [ ] Run the focused tests and confirm they fail because the macOS module and integration do not yet exist.

### Task 2: Extract and implement the macOS sandbox generation

**Files:**
- Create: `src/core/kernel/worker_staging.py`
- Create: `src/core/kernel/worker_macos_sandbox.py`
- Modify: `src/core/kernel/worker_windows_container.py`

**Interfaces:**
- `stage_worker_tree(source: Path, destination: Path, entry_budget: int = 8192) -> int`
- `macos_sandbox_profile(read_paths: tuple[Path, ...], writable_root: Path) -> str`
- `MacOSSandbox.create(...) -> MacOSSandbox`
- `MacOSSandbox.stage(name)`, `MacOSSandbox.spawn(...)`, `MacOSSandbox.close()`

- [ ] Move the existing bounded, link-free tree counter/copy into the shared helper and keep the Windows export aliases compatible.
- [ ] Implement normalized absolute path validation and Seatbelt literal escaping.
- [ ] Implement launcher resolution and fail-closed `sandbox-exec -p profile` spawning with standard pipes and existing process-group keywords.
- [ ] Keep stage/profile/root ownership until explicit close, with idempotent cleanup.
- [ ] Run focused sandbox tests and confirm green.

### Task 3: Wire production runtime selection

**Files:**
- Modify: `src/adapters/subprocess_plugin_runtime.py`
- Modify: `tests/test_subprocess_plugin_runtime.py`

**Interfaces:**
- `SubprocessPluginRuntime(..., macos_sandbox_factory=...)`
- `_should_use_os_isolation()` selects Windows or macOS only for the real Popen; injected factories remain test seams.

- [ ] Add `_spawn_macos_contained()` using the same source/plugin staging and real Broker-root separation as Windows.
- [ ] Route container cleanup through a shared sandbox cleanup path while preserving confirmed termination ordering.
- [ ] Run focused runtime and platform contract tests.

### Task 4: Update evidence and run verification

**Files:**
- Modify: `AGENTS.md`
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/DEVELOPMENT_GUIDE.md`
- Modify: `docs/reports/PROJECT_ANALYSIS.md`
- Modify: `docs/reports/README.md`
- Create: `docs/reports/AUDIT_REPORT_241.md`
- Modify: `tests/run_all.py` if required to register the new contract class

- [ ] Record the exact local contract evidence and state that real macOS enforcement is unverified on the Windows host.
- [ ] Run aggregate, full discovery, Ruff, compileall, frontend checks and diff integrity.
- [ ] Perform final requirement-by-requirement self-review and preserve unrelated changes.

