# AUDIT_REPORT_237.md

**Iteration**: #237
**Date**: 2026-08-30
**Status**: Complete

## Scope

Iteration 236 captured bounded service logs, but its UTF-8-only tail decoder could
still corrupt a real Windows locale-encoded traceback into replacement characters.
The child environment also did not explicitly force Python services to emit UTF-8.
This iteration closes that diagnostics boundary without changing service or profile
failure contracts.

## Changes

- Added strict UTF-8 decoding with locale-encoding fallback and a final replacement
  fallback for service log tails.
- Set `PYTHONIOENCODING=utf-8` alongside `PYTHONUNBUFFERED=1` for Python services.
- Added ten regressions covering UTF-8, ASCII, locale-encoded, undecodable, unknown
  encoding, lookup failure, bounded-tail, real-child output, failure reporting and
  child-environment behavior.
- Registered the new regression classes in the canonical aggregate suite.
- Synchronized the iteration ledger and rolling audit navigation.

## Evidence

Locale-encoded socket errors now retain the Windows error code and readable message
without replacement characters. UTF-8 output remains exact, undecodable bytes still
produce bounded text, and the captured tail remains limited to 4 KiB of raw log data.

## Self-Review

- Strict UTF-8 remains authoritative; locale decoding is attempted only after a
  decoding failure, and codec lookup or decode failures cannot escape diagnostics.
- Python services are explicitly configured for UTF-8, while Node and other children
  remain covered by the locale-aware reader.
- The decoder is used only after the existing bounded binary tail read, so no new
  unbounded log allocation or process authority is introduced.
- The aggregate registration is exact and the updated ledger metrics are checked by
  the existing iteration tests.

## Verification

| Command | Result |
|---|---|
| `python -m unittest tests.test_ci_integration_output_encoding` | 10 passed |
| `python tests/run_all.py` | Total: 1087; passed: 1081; skipped: 6 |
| `python scripts/discover_tests.py --timeout 1800` | 2048 ran; OK (skipped=6); 2041 attributed; exit 0 |
| `python -m ruff check src tests scripts` | Passed; zero findings |
| `python -m compileall -q src tests scripts` | Passed |
| `cd frontend; npm test -- --run` | 151 passed |
| `cd frontend; npm run typecheck` | Passed |
| `cd frontend; npm run build` | Passed |
| `cd frontend; npm run test:e2e` | 7 passed; 1 conditional skip |
| `git diff --check` | Passed |

## Residual Risk

- Service output from a codec that is neither UTF-8 nor the active locale still uses
  replacement decoding, preserving diagnostics availability rather than inventing a
  third unbounded encoding probe.
- `_free_port()` retains a low-probability bind-close-rebind TOCTOU window; it was not
  reproduced in this iteration and remains a separate hardening boundary.
- Windows and macOS still lack an OS-level sandbox equivalent to the Linux Worker
  Landlock and network-namespace boundaries.
