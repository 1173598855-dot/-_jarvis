# Bounded Stream Query Inputs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bound GET Ollama stream query inputs before parsing or upstream dispatch while preserving valid SSE behavior.

**Architecture:** Apply one 32 KiB UTF-8 budget at the standard-library raw query boundary and one FastAPI query validation plus byte check. Keep the existing fallback for malformed JSON and declare the new 413 contract in OpenAPI.

**Tech Stack:** Python stdlib `urllib.parse`, FastAPI/Pydantic `Query`, OpenAPI JSON, unittest.

## Global Constraints

- The exact query budget is 32 KiB (32768 UTF-8 bytes).
- Oversize failures use HTTP 413, code `REQUEST_QUERY_TOO_LARGE`, and message `Request query exceeds the 32 KiB limit`.
- No valid model/messages shape, SSE frame, dependency, or environment variable changes.

---

### Task 1: RED query boundary regressions

**Files:**
- Modify: `tests/test_main.py`
- Modify: `tests/test_main_fastapi_extended.py`

- [x] Add standard-library and FastAPI oversize tests, then run the focused tests and verify the old implementation parses/forwards instead of returning the new 413 envelope.

### Task 2: GREEN service and contract boundary

**Files:**
- Modify: `src/main.py`
- Modify: `src/main_fastapi.py`
- Modify: `contracts/core-api.openapi.json`

- [x] Reject raw and decoded query values before parsing/dispatch in `main.py`.
- [x] Add FastAPI `Query` max length, UTF-8 byte check, validation mapping, and 413 envelope.
- [x] Add OpenAPI `maxLength: 32768` and 413 response declaration.
- [x] Run focused Python/API contract tests.

### Task 3: Self-review, full verification, and ledger

**Files:**
- Modify: `AGENTS.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/DEVELOPMENT_GUIDE.md`
- Modify: `docs/reports/PROJECT_ANALYSIS.md`
- Modify: `docs/reports/README.md`
- Create: `docs/reports/AUDIT_REPORT_205.md`

- [x] Verify raw/decoded byte accounting, exact-limit behavior, validation mapping, and OpenAPI parity.
- [x] Run aggregate/discovery, frontend gates, E2E, compileall, Ruff, integration, ledger, and diff checks.
- [x] Update the rolling window to 196-205 and record actual totals.
