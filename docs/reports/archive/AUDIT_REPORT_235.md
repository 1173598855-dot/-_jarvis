# AUDIT_REPORT_235.md

**Iteration**: #235
**Date**: 2026-08-30
**Status**: Complete

## Scope

Iteration 234 left `unittest discover` as the only Python verification step without a
per-command deadline: `tests/run_all.py` gained `--timeout`, but discovery relied on the
45-minute CI job cap. A wedged test therefore consumed the whole job, truncated the log,
and never named the case that hung. This audit closes that gap and, while validating it,
corrected a truthfulness defect in the new runner's own test accounting.

## Changes

- Added `scripts/discover_tests.py`, a stdlib-only wrapper that runs discovery in a
  controlled child process under a cooperative deadline. It forces `-u -v` so per-test
  progress is available before the deadline, mirrors both streams without whole-run
  buffering, and writes an optional JSON summary shaped like the `run_all.py` report.
- Added hang attribution: `_DiscoveryProgress` tracks the "started but not yet resolved"
  verbose line, so a timeout reports the exact in-flight test plus the last 20 outcomes.
  Cases whose description spans a docstring line are reattached to their test ID.
- Added process-tree reclamation. POSIX runs the child in its own session and kills the
  group; Windows uses `taskkill /T /F`. Killing only the direct child left detached
  grandchildren from Worker tests still running.
- Added an independent 64 MiB raw-byte budget per stream. Overflow keeps draining the
  pipe so the child cannot block on a write, then terminates the tree and fails closed.
- Added authoritative summary parsing after observing that per-test attribution
  undercounts: a test writing a newline to stderr splits the pending progress line. The
  report now carries both unittest's own `Ran N tests` count and the attributed count,
  and the last summary wins so nested runners cannot shadow the outer result.
- Pointed CI at the wrapper with `--timeout 1800 --json-report discover-report.json` and
  widened the artifact upload to both Python reports.
- Added `tests/test_discover_tests_runner.py` (22 tests) and registered its five classes
  in the canonical aggregate list.

## Evidence

A fixture whose case sleeps 120 seconds, run with `--timeout 3`, exited in 3.55 seconds
with exit 1 and `in_flight_test: test_hangs (test_hang.TestHang.test_hangs)`, retaining
`test_fast ... ok` in `recent_tests`. A fixture that spawns a detached grandchild writing
a heartbeat every 0.1 seconds stopped at 21 bytes both at exit and 3 seconds later.

Two control experiments confirm the regressions fail without the fix. Removing `-v` from
the discovery command broke 4 tests, including `in_flight_test` becoming empty. Disabling
the tree kill so only the direct child is signalled failed the grandchild regression with
`grandchild survived the deadline: 30 -> 45 bytes`. After each control run
`scripts/discover_tests.py` was restored and verified byte-identical by sha256.

## Self-Review

- The wrapper is the gate that runs the tests, so it imports only the standard library
  and never the code under test. It deliberately does not reuse `ProcessTreeContainment`.
- `tests_reported` is documented as best-effort attribution; `ran_tests` is authoritative.
  Reporting only the attributed count would have understated the suite by 7 tests.
- Group termination is skipped when the child shares this process group, so the harness
  cannot signal itself.
- Non-zero child exits pass through as failures; timeout and overflow are distinguishable
  in both the banner and the JSON payload.
- `tests/test_ci_workflow.py` asserted the bare discover command, so it was updated in the
  same change and now also asserts the unguarded form is gone.
- The 1034 -> 1056 aggregate growth is entirely the 22 new tests; no existing suite
  membership or report field changed.

## Verification

| Command | Result |
|---|---|
| `python -m unittest tests.test_discover_tests_runner` | 22 passed |
| hang fixture with `--timeout 3` | exited 3.55s; hung test named; exit 1 |
| grandchild fixture with `--timeout 4` | heartbeat frozen at 21 bytes after 3s |
| control without `-v` | 4 regressions failed; attribution empty |
| control without tree kill | grandchild survived: 30 -> 45 bytes |
| `python -m ruff check src tests scripts` | Passed; zero findings |
| `python -m compileall -q src tests scripts` | Passed |
| `python tests/run_all.py` | Total: 1056; passed: 1050; skipped: 6 |
| `python scripts/discover_tests.py --timeout 1800` | 2017 ran; OK (skipped=6); 2010 attributed; exit 0 |
| `cd frontend; npm test -- --run` | 151 passed |
| `cd frontend; npm run typecheck` | Passed |
| `cd frontend; npm run build` | Passed |
| `cd frontend; npm run test:e2e` | 7 passed; 1 conditional skip |
| `git diff --check` | Passed |

## Residual Risk

- Attribution depends on unittest's verbose text format. A future format change would
  degrade hang naming, though the deadline, tree kill and summary count still hold.
- The deadline is whole-run, not per-test, so a suite of many slow-but-finite tests is
  indistinguishable from one wedged test until the report names the in-flight case.
- `scripts/ci_local_integration.py --require-services` still has only the CI job cap.
- Grandchild reclamation is best-effort: a process that escapes both the POSIX group and
  the Windows tree, such as one that re-parents itself, is not tracked.
