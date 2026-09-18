# AUDIT_REPORT_236.md

**Iteration**: #236
**Date**: 2026-08-30
**Status**: Complete

## Scope

Iteration 235 bounded `unittest discover` and recorded the service-integration step as the
last verification without a per-command deadline. This audit closes it. Three defects were
reproduced with measurements before any code changed:

1. `run_integration()` passed `--timeout` to the profile as an argument but called
   `subprocess.run()` with no `timeout`. A profile sleeping 60 seconds under `--timeout 3`
   ran the full 60.0 seconds; only the 45-minute job cap bounded it.
2. `_wait_for_health()` never checked whether the service had already exited. A service
   that exited with code 3 still burned 21.1 seconds of health budget, and the resulting
   error text never mentioned the exit code.
3. Service stdout and stderr went to `DEVNULL`, so a startup failure produced no
   diagnostics, and `_stop()` reaped only the direct child.

## Changes

- Added an overall deadline. `--overall-timeout` (default 300s) bounds the whole run; each
  health wait and the profile take the smaller of their own budget and the remaining time.
  `_remaining()`/`_stage_budget()` raise `IntegrationTimeout` naming the stage that ran out.
- Gave the profile its own deadline via `_run_profile()`, which kills the tree on overrun
  and returns 2 instead of waiting indefinitely.
- Made health waits fail fast: a service observed already exited raises immediately with
  its name and exit code rather than polling a dead port.
- Captured service output into the previously-unused managed temporary directory and print
  a bounded 4 KiB tail on failure. This also gives the formerly dead `name` parameter a use.
- Added tree reclamation (`taskkill /T` on Windows, process group on POSIX) and made
  `_stop()` escalate to it when terminate is ignored. Services now start in their own
  session on POSIX.
- Rejected non-positive and non-integer timeouts instead of accepting `--timeout 0`.
- Added `tests/test_ci_integration_bounds.py` (21 tests) and registered its seven classes
  in the canonical aggregate list.

## Evidence

Two control-revert experiments confirm the regressions fail without the fix. Restoring the
unbounded `process.wait()` failed `test_overrunning_profile_is_killed_at_its_budget` and
`test_a_wedged_profile_cannot_outlive_the_overall_timeout` with `0 != 2`, and the suite took
184.2 seconds instead of 8.4. Disabling the health fail-fast check failed
`test_exited_service_is_reported_before_the_budget_is_spent`: the message degraded to
`Timed out waiting for core ...` with no exit code. After each control run
`scripts/ci_local_integration.py` was restored and verified byte-identical by sha256
(`6f0bbd69d2ba213b`).

## Self-Review

- Patching `Popen` on the shared `subprocess` module also intercepts the reclamation
  helper's own `taskkill` call. The test double therefore routes by service marker and lets
  every other child through; an early version faked all children and raised a context-manager
  TypeError, which is why the routing is explicit.
- Group termination is skipped when the child shares the harness's process group.
- `run_integration()` still returns 2 for failures and the profile's own exit code on
  success, so the CI contract is unchanged. `--require-services` remains mandatory.
- Log capture replaces `DEVNULL` rather than adding a second mechanism, and the temporary
  directory that was previously created and discarded is now the log root.
- The 1056 -> 1077 aggregate growth is entirely the 21 new tests.
- `_free_port()` retains a low-probability, unreproduced bind-close-rebind TOCTOU boundary.

## Verification

| Command | Result |
|---|---|
| `python -m unittest tests.test_ci_integration_bounds` | 21 passed |
| defect 1 reproduction | 60.0s elapsed under `--timeout 3` |
| defect 2 reproduction | 21.1s burned; exit code absent from error |
| control without profile deadline | 2 failures (`0 != 2`); suite 184.2s |
| control without health fail-fast | exit code lost from failure message |
| `python -m ruff check src tests scripts` | Passed; zero findings |
| `python -m compileall -q src tests scripts` | Passed |
| `python tests/run_all.py` | Total: 1077; passed: 1071; skipped: 6 |
| `python scripts/discover_tests.py --timeout 1800` | 2038 ran; OK (skipped=6); 2031 attributed; exit 0 |
| `cd frontend; npm test -- --run` | 151 passed |
| `cd frontend; npm run typecheck` | Passed |
| `cd frontend; npm run build` | Passed |
| `cd frontend; npm run test:e2e` | 7 passed; 1 conditional skip |
| `git diff --check` | Passed |

## Residual Risk

- The bounding tests fake the three services. A real end-to-end integration run still
  happens only in CI, where `--overall-timeout 900` now bounds it.
- `_free_port()` retains a low-probability, unreproduced bind-close-rebind TOCTOU boundary.
- Tree reclamation is best-effort; a process that re-parents itself escapes both the POSIX
  group and the Windows tree.
- Phase 8/11/12 remain in progress, and Windows/macOS still lack an OS-level sandbox
  equivalent to the Linux Landlock and network-namespace boundaries.
