# AUDIT_REPORT_124.md

**Iteration**: #124
**Date**: 2026-07-13
**Status**: Complete

## Goal

Restore evidence-backed parity for the shared orchestrator contract across the
Python HTTPServer, FastAPI, and Express adapters.

## Changes

- FastAPI history requests now clamp `limit` to `1..100`.
- Python HTTPServer orchestrator dispatch now validates and forwards
  `timeout=300` and `priority=1` with priority bounded to `0..3`.
- OpenAPI history `limit` now declares `maximum: 100`.
- The local response-shape validator now enforces numeric `maximum` values.
- The real loopback harness dispatches the same task through Python HTTPServer,
  FastAPI, and Express, validates complete `AgentResult` responses, and checks
  invalid dispatch error envelopes.
- The Express Core fixture now includes `error` and `duration_ms` in successful
  dispatch responses.
- OpenAPI `1.10.0` now declares request defaults, `timeout` range `1..300`,
  non-blank agent/prompt strings, and dispatch `413` responses.
- All adapters reject invalid option types, whitespace-only fields, and
  unpaired Unicode surrogates; Python normalizes valid surrogate pairs.
- Python HTTPServer normalizes extreme JSON parser failures and drains an
  oversized declared body in bounded chunks before returning `413`, avoiding
  Windows connection resets for normal completed uploads.
- Declared bodies within the limit are also read in 8 KiB chunks under a
  two-second total deadline, so a partial local client cannot block the
  single-threaded HTTPServer indefinitely.

## Verification

| Command | Result |
|---|---|
| `python tests/run_all.py` | Passed: 189 tests |
| `python -m unittest discover -s tests -p "test_*.py"` | Passed: 1020 tests |
| `python -m unittest tests.test_api_contract` | Passed: 18 tests |
| `python -m unittest tests.test_main tests.test_main_fastapi` | Passed: 246 tests |
| `python -m compileall -q src tests scripts` | Passed |
| `cd frontend; npm test -- --run` | Passed: 103 tests |
| `cd frontend; npm run test:e2e` | Passed: 5; skipped: 1 desktop-only case |
| `cd frontend; npm run typecheck` | Passed |
| `cd frontend; npm run build` | Passed |
| `git diff --check` | Passed |

## Remaining Work

- Role-specific `/api/roles*` routes remain FastAPI-only and are intentionally
  outside the shared OpenAPI contract until status and payload semantics are
  unified across all adapters.
- Real Ollama workstation validation remains an optional complement to the
  repository-owned deterministic fixture.
