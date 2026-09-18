# AUDIT_REPORT_247.md

**Iteration**: #247
**Date**: 2026-09-07
**Status**: Complete

## Scope

This iteration fixes a Windows-only diagnostic loss in the discovery runner's
end-to-end test fixture. The production discovery runner remains unchanged.

## Changes

- Added a locale-independent reproduction that forces the parent-side default
  subprocess decoder to ASCII while the child emits valid UTF-8.
- Added an arbitrary-byte fixture proving that an invalid UTF-8 byte remains
  visible as a stable `\xff` diagnostic.
- Set the fixture's existing `subprocess.run()` boundary to
  `encoding="utf-8"` and `errors="backslashreplace"`.

## Root Cause

`text=True` selected the Windows process locale for the parent pipe readers.
That locale can differ from `PYTHONIOENCODING` used by the child. A reader
thread then raised `UnicodeDecodeError`, set the captured stream to `None` and
did not necessarily fail the surrounding test.

## Verification

| Command | Result |
|---|---|
| `python tests/run_all.py` | Total: 1155; passed: 1147; skipped: 8 |
| Locale-conflict regression before the fix | Failed with reader-thread `UnicodeDecodeError`; `stderr` became `None` |
| Arbitrary-byte regression before the fix | Failed with reader-thread `UnicodeDecodeError`; `stdout` became `None` |
| `python -m unittest tests.test_discover_tests_runner -v` | 24 passed |
| Focused discovery and aggregate-wiring modules | 66 passed |
| Documentation contract suites | 27 passed |
| `python scripts/discover_tests.py --timeout 1800` | Total: 2128; passed: 2119; skipped: 9 |
| `python -m ruff check src tests scripts` | Passed; zero findings |
| `python -m compileall -q src tests scripts` | Passed |
| Frontend Vitest / Playwright | 151 passed / 7 passed, 1 desktop-conditional skip |
| Frontend typecheck / build | Passed / passed |

## GitHub Intelligence

- CPython issue [#105312](https://github.com/python/cpython/issues/105312)
  documents Windows console and locale code-page divergence for
  `subprocess.run(text=True)`.
- pytest issue [#7623](https://github.com/pytest-dev/pytest/issues/7623) and PR
  [#14963](https://github.com/pytest-dev/pytest/pull/14963) document captured
  subprocess output loss and the diagnostic value of `backslashreplace`.
- No dependency or upstream code was imported; the standard-library boundary
  is sufficient for this fixture.

## Residual Risk

- `backslashreplace` intentionally renders invalid bytes as escapes rather than
  reconstructing their unknown source encoding. The diagnostic remains stable
  and inspectable.
- The production discovery runner is unchanged; this iteration prevents its
  end-to-end regression fixture from masking output-decoding failures.
