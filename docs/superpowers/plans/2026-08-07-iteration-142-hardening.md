# Iteration 142 Protocol Boundary Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the Iteration 141 Plugin Worker protocol against recursive and resource-exhaustion inputs, then verify the complete service and frontend contract without changing the established architecture.

**Architecture:** Keep validation in the protocol contract module before immutable message construction. Preserve the parent-owned Broker and Worker lifecycle boundaries. Use focused regression tests first, then run the existing aggregate, discovery, frontend, and local integration checks.

**Tech Stack:** Python 3.10+ standard library, `unittest`, FastAPI, Express 5, Vitest, Playwright, TypeScript, Vite.

## Global Constraints

- Preserve all unrelated user changes already present in the working tree.
- Do not add runtime dependencies or broaden HTTP authority.
- Reject malformed or resource-exhausting protocol input with a bounded `PluginWorkerProtocolError`.
- Production code changes require a regression test observed failing before implementation.
- Report actual command results and retain the existing ten-report rotation policy.

---

### Task 1: Reproduce the recursive protocol failure

**Files:**
- Modify: `tests/test_plugin_worker_protocol.py`
- Inspect: `src/core/contracts/plugin_worker_protocol.py`

- [x] Run the existing deep-nesting test alone and capture the expected `RecursionError`.
- [x] Trace the call path from `decode_message()` through message construction and identify the first unbounded recursion.

Command:

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_plugin_worker_protocol.TestPluginWorkerProtocol.test_decode_normalizes_deeply_nested_broker_arguments -v
```

### Task 2: Implement bounded protocol decoding

**Files:**
- Modify: `src/core/contracts/plugin_worker_protocol.py`
- Modify: `tests/test_plugin_worker_protocol.py`

- [x] Add or refine a minimal test asserting that deeply nested JSON is rejected as `PluginWorkerProtocolError` with bounded text and no raw recursion traceback.
- [x] Run the test to observe RED for the missing boundary.
- [x] Implement the smallest pre-construction depth guard or bounded normalization path, retaining canonical JSON and exact schema checks.
- [x] Run the focused protocol suite and verify GREEN.

### Task 3: Audit adjacent Worker/Broker and API boundaries

**Files:**
- Inspect: `src/core/contracts/plugin_worker_protocol.py`
- Inspect: `src/core/kernel/plugin_broker.py`
- Inspect: `src/adapters/subprocess_plugin_runtime.py`
- Inspect: `src/runtime/plugin_worker.py`
- Inspect: `src/main.py`
- Inspect: `src/main_fastapi.py`
- Inspect: `frontend/server.js`
- Add tests only where a concrete gap is reproduced.

- [x] Check malformed JSON, oversized values, exception redaction, lifecycle ownership, event commit ordering, request-field allowlists, and API response/error parity.
- [x] For every discovered defect, add a failing regression test before a minimal fix and rerun the narrow suite.
- [x] Run `git diff --check` and Python compilation after fixes.

### Task 4: Self-review and full verification

**Files:**
- Modify: `CHANGELOG.md` and a new `docs/reports/AUDIT_REPORT_142.md` only after implementation evidence is available.

- [x] Re-read the requirements and verify functionality, abnormal flows, API contracts, data flow, and security defaults line by line.
- [x] Run the canonical Python aggregate suite, full Python discovery, compileall, frontend Vitest, Playwright, typecheck, and production build.
- [x] Run local integration when its fixture is available; record skips or environmental blockers exactly.
- [x] Fix any failures and repeat the affected verification until stable.
- [x] Confirm the final diff contains no unrelated rollback or generated artifacts.
