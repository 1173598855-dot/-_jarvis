# AUDIT_REPORT_239.md

**Iteration**: #239
**Date**: 2026-09-04
**Status**: Complete

## Scope

The rolling risk list has carried "Windows and macOS lack an OS-level sandbox" since
Iteration 226 without movement. Before adding a platform, this iteration checked what the
existing isolation evidence actually proves, then closed the Windows filesystem and network
boundary with a mechanism verified against a real child process on this host.

## Corrected Overclaim

`tests/test_worker_filesystem_isolation.py` and `tests/test_worker_network_isolation.py`
pass `platform_name="linux"` with fake ctypes doubles and declare no platform skip. On this
Windows host all of their cases report passed while no kernel enforcement occurred.
`tests/test_worker_resource_limits.py` is the only isolation module with a real
`skipIf(os.name == "nt")`. Iteration 238 propagated the "8 passed" figure into the AGENTS
baseline without confirming its scope. Documentation now states that those cases verify
decision logic and fail-closed behavior, not kernel enforcement.

## Changes

- `prepare_windows_worker_isolation()` creates or adopts an AppContainer profile, derives
  the SID, converts it to text, grants caller-owned read paths and exactly one writable
  Worker root through `icacls`, and returns a capability-free identity. Any failure closes
  the identity, deleting a profile only when this call created it.
- `isolated_python_executable()` returns the base interpreter, because an AppContainer
  child launched from the venv cannot read `pyvenv.cfg` and exits before `main()`.
- `default_runtime_read_paths()` reports the runtime paths a child must read. It is
  deliberately not granted: `icacls` against the system Python and the venv is denied
  without elevation, and both already allow `ALL APPLICATION PACKAGES` read/execute.

## Evidence

Measured against a real child in a real container, capability-free:

| Operation | Without AppContainer | With AppContainer |
|---|---|---|
| read a file outside the granted root | `classified` | `errno 13` |
| write inside the granted Worker root | `ok` | `ok` |
| connect to a loopback listener | `ok` | `OSError`, no connection |

The network denial surfaces as an `OSError` without a stable errno rather than
`WSAEACCES 10013`, so the test asserts that the connection did not succeed and that a
failure was recorded, instead of pinning a code that was not reproducible.

Mutation: forcing `EXTENDED_STARTUPINFO_PRESENT` off makes the enforcement case fail with
`{'read': 'classified', 'write': 'ok', 'net': 'ok'}`. The guard therefore measures the
container, not the ambient environment.

## Self-Review

- The overclaim was corrected before the feature was added, so the new real-enforcement
  cases are not read as validating the Linux mocks.
- Both the allowed write and the denied read/connect are asserted together. A sandbox that
  also broke the Worker's own temporary root would be a regression, not a success.
- Profile reclamation is exercised through the failure paths, and `close()` is idempotent
  and never deletes a profile the call adopted rather than created.
- The writable grant is asserted to be last and distinct from the read grants, so a later
  change cannot silently widen the writable surface.
- This module is parent-applied and deliberately separate from the child-applied Linux
  modules. Windows has no in-child equivalent; that asymmetry is real, not an oversight.

## Verification

| Command | Result |
|---|---|
| `python -m unittest tests.test_worker_windows_isolation` | 13 passed |
| `python tests/run_all.py` | Total: 1116; passed: 1110; skipped: 6 |
| `python scripts/discover_tests.py --timeout 1800` | 2079 ran; OK (skipped=6); exit 0 |
| `python -m ruff check src tests scripts` | Passed; zero findings |
| `python -m compileall -q src tests scripts` | Passed |
| `cd frontend; npm test -- --run` | 151 passed |
| `cd frontend; npm run typecheck` | Passed |
| `cd frontend; npm run build` | Passed |
| `cd frontend; npm run test:e2e` | 7 passed; 1 conditional skip |
| `git diff --check` | Passed |

## Residual Risk

- The boundary is proven and available but not yet wired into
  `SubprocessPluginRuntime`. Production Workers still spawn through
  `subprocess.Popen`, so no shipped Worker is inside an AppContainer yet. Integration needs
  parent-owned inheritable pipes and `CREATE_SUSPENDED` before the Job Object assignment,
  and 57 Plugin Worker lifecycle tests depend on the current `Popen` object.
- Linux still has no real-enforcement test. Proving Landlock and the network namespace
  actually deny requires a Linux host, which this environment does not provide.
- macOS remains uncovered. `sandbox-exec` is deprecated and App Sandbox needs code signing;
  shipping an unverified SBPL profile would recreate the overclaim this iteration removed.
- Grants are applied with `icacls` and persist on the granted paths. The enforcement test
  grants only inside its own temporary tree.
