# AUDIT_REPORT_119.md

**Iteration**: #119
**Date**: 2026-07-13
**Status**: Complete

## Goal

Continue the protocol-led hardening and reliability pass by removing a remaining
non-streaming Ollama contract gap, bounding telemetry collection, and reducing
the internal terminal executor's inherited process surface.

## Changes

- Validated non-streaming Ollama responses against the shared successful-response
  shape before Python HTTPServer, FastAPI, or Express return them to clients.
  Upstream HTTP failures, connection failures, malformed JSON, and semantically
  incomplete `200` responses now consistently become `502 OLLAMA_UPSTREAM_ERROR`.
- Added a live three-service fixture regression for incomplete upstream chat
  responses, preventing response-shape drift between the three adapters.
- Bounded every Express telemetry provider probe. Slow probes now time out and
  make only their own fields unavailable instead of blocking the endpoint.
- Made the default internal `TerminalExecutor` run from an executor-owned
  temporary directory with a minimal environment, and reject caller-provided
  working-directory or environment overrides. Its lifecycle now has explicit
  cleanup in FastAPI and Python HTTPServer shutdown paths.

## Verification

| Command | Result |
|---|---|
| `python tests/run_all.py` | Passed: 158 tests |
| `python -m unittest discover -s tests -p "test_*.py"` | Passed: 949 tests |
| `python -m compileall -q src tests` | Passed |
| `cd frontend; npm test -- --run` | Passed: 75 tests |
| `cd frontend; npm run test:e2e` | 5 passed; 1 skipped by project condition |
| `cd frontend; npm run typecheck` | Passed |
| `cd frontend; npm run build` | Passed |

## Remaining Work

- The internal executor is now process-surface constrained, but it is not an
  OS-level low-privilege worker. Future script-capability work must use a
  separately restricted worker or container and must not expose the executor as
  a general HTTP or plugin command API.
- The optional real-service profile still needs a prepared Ollama/Core API CI
  environment using `--require-services`.
- Frontend Chat and Runtime chunk changes should be driven by measured
  interaction latency on low-end hardware.
