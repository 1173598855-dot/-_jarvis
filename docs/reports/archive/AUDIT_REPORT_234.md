# AUDIT_REPORT_234.md

**Iteration**: #234
**Date**: 2026-08-30
**Status**: Complete

## Scope

This audit closes three defects in the test-suite runner. The Python helpers accepted
`timeout` and `json_report`, but the command-line entrypoint ignored all arguments
and always ran the aggregate suite. The timeout helper returned at its deadline while
a non-daemon worker kept the interpreter alive until a hung test finished. Report
titles also used the generic `TestSuite` name and retained stale Iteration 141 text.

## Changes

- Added `build_argument_parser()` and `main(argv=None)` to expose `--smoke`,
  `--timeout SECONDS` and `--json-report PATH` from `tests/run_all.py`.
- Added truthful aggregate and smoke titles with suite label, class count and test
  count; removed the stale Iteration 141 label.
- Made the worker daemonized so in-process helpers return at the deadline, and gated
  the CLI-only timeout branch behind `abandon_on_timeout=True`, flushing the report
  before `os._exit(1)`. Direct library helpers still return 1 without killing their
  host process.
- Added 7 runner regressions covering CLI parsing, invalid values, title contracts,
  real __main__ dispatch, daemonization and prompt timeout termination. The coverage
  module now has 38 tests and remains outside the canonical aggregate list.
- Updated CI to run `run_all.py --timeout 1800 --json-report run-all-report.json`,
  upload the report, and cap the Python contract job at 45 minutes. The job cap also
  bounds `unittest discover`, which has no native timeout option.

## Evidence

A 120-second sleeper invoked through the CLI with `--timeout 2` exited in 2.4 seconds
with exit 1 and a report containing `timeout_expired: true`. The smoke CLI selected 36
cases and wrote `J.A.R.V.I.S. test suite - smoke (5 classes, 36 tests)`. Invalid `-1`,
`abc` and `1.5` values exit 2. Before the fix, a 30-second sleeper with a one-second
helper deadline kept its process alive for 30.4 seconds, and all three CLI flags were
ignored.

## Self-Review

- `os._exit(1)` is reachable only from the CLI path; in-process timeout tests remain
  safe. The hard exit intentionally skips atexit cleanup after an already-failed run.
- The subprocess regression exercises the file entrypoint rather than only calling
  `main()`, so a bare `__main__` call is detected.
- Existing report fields and helper return contracts remain unchanged. Only title
  content is corrected and extended.
- The aggregate count stays 1034; runner coverage remains discovery-only.
- The 45-minute CI job timeout is the final bound for the unguarded discovery and
  service-integration steps.

## Verification

| Command | Result |
|---|---|
| `python -m unittest tests.test_run_all_coverage` | 38 passed |
| CLI smoke subprocess | 36 selected; report written |
| CLI timeout subprocess | 120-second hang exited in 2.4 seconds; exit 1 |
| invalid CLI timeout values | all rejected with exit 2 |
| control without daemon/hard-exit | daemon regression failed; process waited 63.8 seconds |
| control with bare __main__ | entrypoint regression errored after 61.5 seconds |
| `python -m ruff check src tests scripts` | Passed; zero findings |
| `python -m compileall -q src tests scripts` | Passed |
| `python tests/run_all.py` | Total: 1034; passed: 1028; skipped: 6 |
| `python -m unittest discover -s tests -p "test_*.py"` | 1995 total; 1989 passed; 6 skipped |
| `cd frontend; npm test -- --run` | 151 passed |
| `cd frontend; npm run typecheck` | Passed |
| `cd frontend; npm run build` | Passed |
| `cd frontend; npm run test:e2e` | 7 passed; 1 conditional skip |
| `git diff --check` | Passed |

## Residual Risk

- `unittest discover` has only the CI job-level timeout, not a per-command cooperative
  timeout or dedicated failure report.
- A timed-out in-process test cannot be interrupted safely; its daemon thread is
  abandoned while the caller receives failure.
