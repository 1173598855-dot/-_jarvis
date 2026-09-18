# AUDIT_REPORT_246.md

**Iteration**: #246
**Date**: 2026-09-07
**Status**: Complete

## Scope

This iteration closes the evidence gap between Iteration 245's real Linux
namespace/Landlock primitive probe and the production Plugin launch path. The
new opt-in probe must exercise a real `SubprocessPluginRuntime` lifecycle and
prove that its child-applied kernel boundary is active before Plugin code runs,
without adding a production test hook or expanding Plugin authority.

## Changes

- Added a Linux-only, explicit-opt-in production Runtime probe. A purpose-built
  Plugin runs through `start`, `LOAD`, `ACTIVATE`, Broker event commit and
  `close` in a distinct Worker process.
- Established an unprivileged pre-isolation baseline for an outside file and a
  live parent loopback listener plus a DAC-writable Plugin-root marker. The
  Plugin then proves outside read/write, Plugin-root write and loopback denial
  while writing inside `tempfile.gettempdir()` succeeds.
- Returned the frozen result through the existing `event.emit` capability and
  asserted lifecycle status, Plugin event provenance, Worker PID separation,
  confirmed process-tree termination and Worker-root reclamation.
- Registered the probe in the canonical aggregate suite with an honest Windows
  skip and extended the Ubuntu 22.04 `linux-sandbox` job to run both real Linux
  probes under separate explicit environment switches.
- Added platform-independent harness regressions. Outer stdout/stderr are
  concurrently limited to 8 KiB each; timeout, overflow and collection errors
  terminate sidecar/`/proc`-identified Worker groups before the driver group
  and require bounded exit confirmation.
- Normalized the already-modified `plugin_worker.py` line endings through Ruff
  after its mixed buffer triggered Ruff 0.16.2's JSON source-map renderer. No
  Worker, Broker, lifecycle or capability behavior changed.

## Self-Review

- The driver establishes all three outside-access baselines before Runtime
  construction and uses UID/GID 12345 when the outer test starts as root.
- The Plugin declares only `event_bus`, receives only `event.emit`, and sends
  one bounded `plugin.linux_runtime_probe` event. Its fixture initially used an
  invalid non-`plugin.*` event type; the first WSL2 run exposed the stable
  `invalid_arguments` Broker denial and the fixture was corrected without a
  production change.
- The test uses real repository objects and the production Worker entrypoint;
  no fake denial, isolation injection, protocol operation or bypass was added.
- Lifecycle deadlines are fixed, the outer driver has a 20-second deadline,
  and each raw output stream is capped at 8 KiB before decoding.
- Runtime, EventBus, listener, both independent process groups and temporary
  tree ownership have explicit success and failure cleanup. The emitted Worker
  path is present before `close()` and its owned root is absent afterward.
- A Plugin-root marker is DAC-writable to the driver before isolation but
  remains unchanged after the Plugin's denied write, directly proving that the
  production Landlock grant stays read-only.
- Iteration 245's primitive probe remains independent and runs beside the new
  production-chain probe rather than being replaced by it.

## Verification

| Command | Result |
|---|---|
| `python tests/run_all.py` | Total: 1153; passed: 1145; skipped: 8 |
| `python scripts/discover_tests.py --timeout 1800 --json-report .test-discover-246.json` | 2126 total; 2117 passed; 9 skipped; exit 0 without timeout or output truncation |
| `python -m unittest tests.test_linux_plugin_runtime_enforcement tests.test_run_all_coverage tests.test_ci_workflow -v` | 51 total; 50 passed; 1 expected Windows skip |
| `python -m ruff check src tests scripts` | Passed; zero findings |
| `python -m compileall -q src tests scripts` | Passed |
| `JARVIS_RUN_LINUX_PLUGIN_RUNTIME_ENFORCEMENT=1 python3 -m unittest tests.test_linux_plugin_runtime_enforcement -v` (Ubuntu 24.04 WSL2, UID/GID 12345) | 4 passed; harness bounds plus production lifecycle and real kernel denial verified |
| Both opt-ins with the complete `linux-sandbox` module command (Ubuntu 24.04 WSL2) | 24 passed |
| `cd frontend; npm test -- --run` | 151 passed |
| `cd frontend; npm run typecheck` | Passed |
| `cd frontend; npm run build` | Passed |
| `cd frontend; npm run test:e2e` | 7 passed; 1 desktop-conditional skip |

## Residual Risk

- The non-skipped production Runtime result is from Ubuntu 24.04 on WSL2. The
  Ubuntu 22.04 GitHub Actions job remains the independent native hosted-runner
  evidence path.
- The fixed Terminal Worker uses the same Linux isolation primitives but does
  not yet have an equivalent real production-chain probe.
- macOS Seatbelt kernel enforcement still depends on a non-skipped run of its
  dedicated macOS job.
- The supplemental `scripts/ruff_check.py` formatter gate still encounters a
  pre-existing mixed-line-ending file elsewhere in the dirty worktree
  (`src/main_fastapi.py`); the authoritative CI lint command is green.
