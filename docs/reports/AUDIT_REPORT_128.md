# AUDIT_REPORT_128.md

**Iteration**: #128
**Date**: 2026-07-15
**Status**: Complete

## Goal

Prevent role profile tool declarations from becoming ambient authority by
adding a default-deny authorization and invocation boundary before any
model-driven tool loop is enabled.

## Changes

- Added exact per-role grants with no wildcard or implicit fallback.
- Added a broker that requires profile declaration, explicit grant, and a
  registered handler before invoking a tool.
- Added immutable decisions and a thread-safe bounded audit history with stable
  `allowed`, `tool_not_declared`, `tool_not_granted`, and
  `tool_not_registered` reasons.
- Updated `AgentFactory` to expose only authorized tool names and to state tool
  access is disabled under the default empty broker.
- Split task metadata into `declared_tools` and `authorized_tools`.
- Kept automatic model-driven tool invocation, terminal access, and plugin
  lifecycle access disabled.
- Evaluated Kontext CLI and Doberman Core without adding a runtime dependency.

## Verification

| Command | Result |
|---|---|
| `python -m unittest tests.test_role_tools tests.test_agent_factory tests.test_agent_factory_extended -v` | Passed: 68 tests |
| `python tests/run_all.py` | Passed: 208 tests |
| `python -m unittest discover -s tests -p "test_*.py"` | Passed: 1080 tests |
| `cd frontend; npm test -- --run` | Passed: 112 tests |
| `cd frontend; npm run test:e2e` | Passed: 5; skipped by project condition: 1 |
| `cd frontend; npm run typecheck` | Passed |
| `cd frontend; npm run build` | Passed |

## Security Review

- Denied calls are rejected before handler lookup and execution.
- Exact role/tool strings are used; no wildcard grants or dynamic imports exist.
- The new module introduces no subprocess, shell, network, deserialization, or
  filesystem operations.
- Invalid policy, handler, and audit-limit configuration fails during broker
  construction rather than widening access.

## Remaining Work

- Add a bounded model tool-request loop that can invoke only broker-authorized,
  fixed read-only handlers.
- Move timed role execution to a worker boundary that can confirm termination
  before recovery.
