# AUDIT_REPORT_240.md

**Iteration**: #240
**Date**: 2026-09-04
**Status**: Complete

## Scope

Iteration 239 established and real-child-verified a parent-owned Windows
AppContainer identity, but production `SubprocessPluginRuntime` still used
ordinary `subprocess.Popen`. This iteration completes that launch integration
and audits its failure cleanup, process ownership, staging boundary and
evidence records.

## Changes

- `SubprocessPluginRuntime` selects the parent-owned container path for the real
  Windows `subprocess.Popen`. Explicit `os_isolation=False` remains available
  for direct compatibility paths, and injected factories keep the branch
  testable on non-Windows hosts.
- `WindowsWorkerContainer` stages the trusted Worker sources and the Plugin
  into a private tree before launch. Only the staged code tree is granted
  read/execute access; exactly one container-owned Worker root is writable.
- `AppContainerPopen` creates the child suspended with a capability-free
  `SECURITY_CAPABILITIES` attribute and the explicit standard-handle list.
  `ProcessTreeContainment` is attached before the primary thread resumes.
- The parent Broker continues to bind the validated real Plugin root; only the
  staged Plugin root is passed to the child. Container, staging, SID/profile,
  containment and suspended-thread setup failures fail closed without direct
  spawn fallback.
- SID conversion releases the returned SID and deletes only a profile created
  by the current attempt. Container and staged-validation failures release
  already-created identity and stage resources.

## Requirement Matrix

| Requirement | Evidence |
|---|---|
| Parent-applied Windows boundary | `prepare_windows_worker_isolation()` plus `AppContainerPopen` |
| Empty capability set | `SECURITY_CAPABILITIES.Capabilities` remains null with count zero |
| Read-only staged code | bounded, link-free staging and read/execute grant on `code` |
| One writable Worker root | container contract asserts one distinct writable grant |
| Ownership before resume | runtime attaches `ProcessTreeContainment` before `resume()` |
| No silent fallback | contained setup errors close resources and raise `PLUGIN_WORKER_START_FAILED` |
| Broker root separation | parent binds the real root; child receives the staged root |
| Profile/SID cleanup | SID-conversion, grant and identity close regressions |
| Honest platform evidence | Windows real-enforcement tests are conditional; Linux mock suites are documented as decision-logic coverage; macOS remains uncovered |

## Self-Review

- Existing direct/POSIX spawning and the public Broker and Worker wire protocol
  remain unchanged when the container branch is not selected.
- The runtime does not use the real Windows branch merely because a test
  monkeypatch replaced `subprocess.Popen`; an injected factory is the explicit
  test seam. Explicit `os_isolation=False` wins over all automatic selection.
- The container is stored before staging, so every failure after creation can
  close the identity and private stage. The staged Worker path is validated
  again before spawn, and a suspended thread handle is closed on resume or
  failure.
- Termination keeps process-tree containment and the container alive until
  direct process exit, reader shutdown and containment emptiness are confirmed.
- The base interpreter is used because an AppContainer child cannot read the
  venv bootstrap files; shared runtime paths rely on their existing
  `ALL APPLICATION PACKAGES` read/execute ACL rather than an elevated ACL
  mutation. The staged source and Plugin remain parent-owned.
- Linux still has only decision-logic/fail-closed tests for its network and
  filesystem setup, not a kernel-enforcement test. macOS has no equivalent
  parent-owned OS sandbox in this iteration.

## Verification

| Command | Result |
|---|---|
| `python -m unittest tests.test_worker_windows_isolation tests.test_worker_windows_container tests.test_subprocess_plugin_runtime` | 82 passed |
| `python tests/run_all.py` | Total: 1125; passed: 1119; skipped: 6 |
| `python scripts/discover_tests.py --timeout 1800` | 2091 ran; OK (2085 passed, 6 skipped); exit 0 |
| `python -m ruff check src tests scripts` | Passed; zero findings |
| `python -m compileall -q src tests scripts` | Passed |
| `cd frontend; npm test -- --run` | 151 passed |
| `cd frontend; npm run typecheck` | Passed |
| `cd frontend; npm run build` | Passed |
| `cd frontend; npm run test:e2e` | 7 passed; 1 conditional skip |
| `git diff --check` | Passed |

## Residual Risk

- The Windows boundary is now wired into production Plugin Worker launch, but
  this host's direct runtime lifecycle tests use test doubles and the
  Windows-only real-enforcement suite remains the evidence for kernel denial.
- Linux needs a Linux host test that launches a real Worker under its network
  namespace and Landlock rules. macOS remains uncovered for an equivalent
  parent-owned filesystem and network sandbox.
- The runtime still uses the same-user process model. The AppContainer
  capability set is empty, so future capabilities require a separate reviewed
  Broker and grant contract rather than an implicit expansion here.
