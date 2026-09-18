# Chunked Request-Body Limit Implementation Plan

> **For agentic workers:** Execute this plan inline under the active continuous-iteration instruction.

**Goal:** Extend FastAPI's 32 KiB request-body boundary to headerless/chunked ASGI streams.

**Architecture:** Keep the declared-length fast path from Iteration 115. Wrap `receive` with a byte counter, emit the existing 413 envelope on overflow, and guard downstream sends after the middleware responds.

**Tech Stack:** FastAPI/Starlette ASGI middleware, Python asyncio, unittest.

## Global Constraints

- The maximum is exactly 32 KiB; a body ending at that exact size is permitted.
- Headerless/chunked overflow returns the existing non-sensitive `REQUEST_BODY_TOO_LARGE` response.
- Do not add dependencies, change Express/Python HTTPServer behavior, or disturb unrelated dirty changes.

---

### Task 1: Reproduce headerless overflow

**Files:**

- Modify: `tests/test_main_fastapi.py`

- [x] **Step 1: Write a failing ASGI middleware test**

Create a two-message headerless request: 32 KiB with `more_body: true`, then one byte. Require the downstream receive result to be `http.disconnect` and the captured response to be JSON 413 with `REQUEST_BODY_TOO_LARGE`.

- [x] **Step 2: Run red**

Run: `./venv/Scripts/python.exe -m unittest tests.test_main_fastapi.TestRequestBodyLimitMiddleware.test_rejects_headerless_chunked_overflow`

Expected: downstream receives `http.request` because the current middleware checks only `Content-Length`.

### Task 2: Implement and verify the receive guard

**Files:**

- Modify: `src/main_fastapi.py`
- Modify: `tests/test_main_fastapi.py`
- Modify: `tests/run_all.py`
- Modify: `tests/test_run_all_coverage.py`

- [x] **Step 1: Add the counting receive wrapper**

Track byte total in `_RequestBodyLimitMiddleware`. On an over-limit or exactly-limit-plus-more-body message, send the existing 413 response through the original sender, mark the request rejected, yield `http.disconnect`, and drop any later downstream sends.

- [x] **Step 2: Run green**

Run the Task 1 command plus `./venv/Scripts/python.exe -m unittest tests.test_api_contract tests.test_main_fastapi`. Expected: PASS.

### Task 3: Record Iteration 116

**Files:**

- Modify: `AGENTS.md`, `CHANGELOG.md`, `docs/reports/GITHUB_LEARNING_REPORT.md`, `docs/reports/PROJECT_ANALYSIS.md`, `docs/reports/README.md`
- Create: `docs/reports/AUDIT_REPORT_116.md`
- Delete: `docs/reports/AUDIT_REPORT_106.md`

- [x] **Step 1: Record research and test evidence**

Record Uvicorn (10,825 Stars, BSD-3-Clause) and h11 (560 Stars, MIT) as active unarchived references, with a no-dependency decision.

- [x] **Step 2: Run delivery gate and record exact counts**

Run aggregate/discovery Python suites, compileall, Vitest, Playwright, typecheck, build, and `git diff --check`; retain audits 107-116.
