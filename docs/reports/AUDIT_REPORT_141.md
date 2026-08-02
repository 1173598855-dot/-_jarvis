# AUDIT_REPORT_141.md

**Iteration**: #141
**Date**: 2026-08-02
**Status**: Complete

## Goal

Move first-party executable Python Plugins behind a parent-owned Worker and
Broker boundary while preserving the existing Plugin lifecycle response shapes.

## Delivered Behavior

- `python_worker` is the only executable V1 Plugin runtime. Plugin source is
  loaded in a service-owned same-user subprocess, never imported by the parent
  service process.
- The parent-owned Broker is default-deny. Its only V1 authority is the
  explicitly granted `event.emit` capability, which publishes a bounded event
  through the parent EventBus.
- Shared OpenAPI `1.16.0` documents the existing Worker-isolated lifecycle
  routes without adding caller-controlled Worker fields or new HTTP authority.
- First-party manifests and lifecycle handling use the Worker protocol,
  generation tracking, termination confirmation, and parent-side audit data.
- The boundary is implemented by `src/core/contracts/plugin_worker_protocol.py`,
  `src/core/kernel/plugin_broker.py`, `src/runtime/plugin_worker.py`,
  `src/adapters/subprocess_plugin_runtime.py`, and `src/core/kernel/plugin_sdk.py`.
- Worker-local API calls now reach the Broker even when the requested V1
  capability is unavailable, so the parent returns the structured
  `PLUGIN_BROKER_DENIED` result instead of a child-local lifecycle failure.
- Load, enable, and disable retain response compatibility. No new HTTP
  authority was introduced.

## Verification

| Command | Result |
|---|---|
| `python tests/run_all.py` | Total: 565; passed: 563; skipped: 2 |
| `python -m unittest discover -s tests -p "test_*.py"` | Total: 1471; passed: 1469; skipped: 2 |
| `python -m compileall -q src tests scripts` | Passed |
| `cd frontend; npm test -- --run` | Passed: 142 tests |
| `cd frontend; JARVIS_E2E_PORT=5189; npm run test:e2e` | Passed: 7; skipped: 1 conditional desktop case |
| `cd frontend; npm run typecheck` | Passed |
| `cd frontend; npm run build` | Passed |
| `python scripts/ci_local_integration.py --require-services` | Passed |
| `git diff --check` | Passed |

## Scope Boundary

Workers are same-user subprocesses. V1 does not provide OS-level filesystem or
network isolation, an independent dependency environment, or any Broker
authority beyond `event.emit`. Stage E retains those isolation controls as
remaining work.
