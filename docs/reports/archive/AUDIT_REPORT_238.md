# AUDIT_REPORT_238.md

**Iteration**: #238
**Date**: 2026-09-04
**Status**: Complete

## Scope

Iteration 237 closed the diagnostics decoding boundary and recorded the runner's
`_free_port()` bind-close-rebind window as a separate hardening boundary. This iteration
closes that window and, while verifying it with real service runs, found and fixed a
second defect in the same runner: temp-directory cleanup could turn an already-passing
profile into exit 2.

## Changes

- Added `_PortReservation` and `_reserve_ports()`. Three loopback ports are held bound at
  once, making them distinct by construction, and each reservation is released
  immediately before the child that binds it.
- Reservations request `SO_EXCLUSIVEADDRUSE` where available and call `listen(1)` so a
  `SO_REUSEADDR` socket cannot take a held port; the reservation never sets
  `SO_REUSEADDR`. `release()` is idempotent and the `finally` path releases any
  reservation whose service never started.
- Replaced `TemporaryDirectory` with `mkdtemp` plus `_remove_log_dir()`, which retries a
  bounded number of times and then warns with the leftover path instead of raising.
- Added `tests/test_ci_integration_resource_ownership.py` with 16 regressions and
  registered its four classes in `tests/run_all.py`.

## Evidence

The cleanup defect is reproducible, not theoretical. Three pre-change runs of the
current runner produced `exit2 winerr32=true profilePassed=true`, `exit0`,
`exit2 winerr32=true profilePassed=true`: the profile printed
`"status": "passed"` and the run still exited 2 because cleanup raised
`[WinError 32]` on `ollama-fixture.log`. Five consecutive post-fix runs exit 0 with no
warning emitted.

The per-child release ordering is mutation-checked. Releasing all three reservations up
front instead of before each child makes
`test_each_reservation_is_released_before_its_service_starts` fail with the exact
interleaving diff, so the guard is not vacuous.

## Self-Review

- The reservation only ever narrows the unowned window; it does not change any port
  number the services receive, nor the health, deadline, tree-reclamation or log-tail
  contracts.
- `release()` is idempotent, so releasing before a child and again in `finally` is safe,
  and a reservation whose service never started is still closed.
- `_reserve_ports()` releases every already-held reservation when a later one fails or
  when distinctness does not hold, so no socket leaks on the failure path.
- Cleanup is deliberately non-fatal: it can only add a warning, never change an exit
  code. A genuine service failure still returns 2 through the existing path.
- The 16 regressions patch the runner module's own `socket`, `shutil` and `time`
  references rather than global state, and the two socket-level tests assert real bind
  refusal instead of trusting the option call.

## Verification

| Command | Result |
|---|---|
| `python -m unittest tests.test_ci_integration_resource_ownership` | 16 passed |
| `python -m unittest tests.test_ci_integration_bounds tests.test_ci_integration_output_encoding tests.test_ci_integration_resource_ownership tests.test_discover_tests_runner` | 69 passed |
| `python scripts/ci_local_integration.py --require-services --timeout 60 --overall-timeout 240` | exit 0 on 5 consecutive runs |
| `python tests/run_all.py` | Total: 1103; passed: 1097; skipped: 6 |
| `python scripts/discover_tests.py --timeout 1800` | 2065 ran; OK (skipped=6); exit 0 |
| `python -m ruff check src tests scripts` | Passed; zero findings |
| `python -m compileall -q src tests scripts` | Passed |
| `cd frontend; npm test -- --run` | 151 passed |
| `cd frontend; npm run typecheck` | Passed |
| `cd frontend; npm run build` | Passed |
| `cd frontend; npm run test:e2e` | 7 passed; 1 conditional skip |
| `git diff --check` | Passed |

## Residual Risk

- The unowned window is narrowed to the release-then-exec handoff, not eliminated. A
  service that fails to bind still surfaces through the existing health-wait failure.
- `tests/test_api_contract.py` keeps its own local `_free_port()` helper for a
  single short-lived Express probe; it was not migrated because it binds immediately and
  is not part of the required-services runner.
- If Windows never releases a log handle, the directory is left in the system temp area
  and only reported as a warning. That is the deliberate trade: diagnostics availability
  over overwriting a real result.
- Windows and macOS still lack an OS-level sandbox equivalent to the Linux Worker
  Landlock and network-namespace boundaries.
