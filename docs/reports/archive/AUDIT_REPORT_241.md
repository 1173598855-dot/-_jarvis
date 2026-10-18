# AUDIT_REPORT_241.md

**Iteration**: #241
**Date**: 2026-09-05
**Status**: Complete

## Scope

Iteration 240 wired the parent-owned Windows AppContainer path into
`SubprocessPluginRuntime`. This iteration extends the same production Worker
boundary to macOS with a parent-owned `sandbox-exec`/Seatbelt profile, bounded
link-free staging, explicit cleanup ownership, and honest platform evidence.

## Changes

- Added `MacOSSandbox`, which creates a private staging root, generates a
  Seatbelt profile beginning with `(deny default)`, omits network allowances,
  allows reads for staged code/runtime paths, and allows writes only below one
  Worker-owned root.
- Added shared `stage_worker_tree()` with an 8,192-entry budget and link
  rejection before copying. The Windows container keeps its public staging
  wrapper while reusing the shared implementation.
- Wired `SubprocessPluginRuntime` to select the macOS boundary for real macOS
  Popen launches or an injected test factory. Explicit `os_isolation=False`
  continues to select direct compatibility spawning.
- Preserved Broker root separation: the parent binds the validated real Plugin
  root while the child receives only the staged Plugin path. Sandbox, staging,
  launch, process containment and cleanup failures fail closed without a
  direct-spawn fallback when isolation is selected.
- Added contract coverage for profile contents, Seatbelt literal escaping,
  invalid paths, staging limits, launcher failure cleanup, runtime selection
  and macOS fail-closed startup.

## Requirement Matrix

| Requirement | Evidence |
|---|---|
| Default-deny profile | `macos_sandbox_profile()` starts with `(deny default)` |
| No network access | No `network-*` allowance is emitted; contract test asserts both absent |
| Bounded link-free staging | Shared `stage_worker_tree()` with 8,192-entry budget and link rejection |
| One writable root | Profile emits one `file-write*` allowance for the Worker root |
| Safe profile paths | Absolute, normalized, control-free paths and escaped Seatbelt literals |
| No fallback | Runtime tests assert staging failure closes the sandbox and never calls direct Popen |
| Broker separation | Parent real root remains bound; child arguments use staged Plugin root |
| Honest evidence | Windows host verifies contract/fail-closed logic only; macOS kernel enforcement is unverified |

## Self-Review

- The runtime keeps the existing ProcessTreeContainment and cleanup ordering.
  The parent-owned sandbox remains held until process exit, reader shutdown and
  containment cleanup are complete.
- Automatic macOS setup failures are surfaced as the stable Worker start
  failure; no ordinary spawn fallback is available on that path.
- Staged code and Plugin paths are separate from the real Broker root. The
  shared staging helper is also used by Windows so the entry and link boundary
  does not fork between platforms.
- The test suite does not claim kernel denial on this Windows host. A future
  macOS host or CI runner must verify actual Seatbelt enforcement, and
  `sandbox-exec` deprecation remains a documented residual risk.

## Verification

| Command | Result |
|---|---|
| `python -m unittest tests.test_worker_macos_sandbox tests.test_subprocess_plugin_runtime` | 88 passed |
| `python tests/run_all.py` | Total: 1130; passed: 1124; skipped: 6 |
| `python tests/run_all.py --timeout 1800 --json-report .test-i241-aggregate.json` | Total: 1130; passed: 1124; skipped: 6 |
| `python scripts/discover_tests.py --timeout 1800 --json-report .test-i241-discovery.json` | 2098 ran; OK (2092 passed, 6 skipped) |
| `python -m ruff check src tests scripts` | Passed; zero findings |
| `python -m compileall -q src tests scripts` | Passed |
| `cd frontend; npm test -- --run` | 151 passed |
| `cd frontend; npm run typecheck` | Passed |
| `cd frontend; npm run build` | Passed |
| `cd frontend; npm run test:e2e` | 7 passed; 1 conditional skip |
| `git diff --check` | Passed |

## Residual Risk

- `sandbox-exec` is deprecated and may be unavailable or restricted on future
  macOS releases; absence is fail-closed, but the production path needs a
  macOS-host verification job.
- Linux network namespace and Landlock suites remain decision-logic and
  fail-closed coverage on this Windows host rather than kernel-enforcement
  evidence.
- The Worker remains same-user code; capabilities continue to flow through the
  parent-owned default-deny Broker rather than the sandbox profile.
