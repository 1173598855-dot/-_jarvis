# Bounded Core API Responses Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bound every Express Core API response before JSON parsing and keep
the request deadline active through body consumption.

**Architecture:** Retain Fetch and add one private raw-byte reader in
`frontend/server/core-api.js`. The reader enforces an 8 MiB cumulative budget,
cancels overflow, and cooperates with the existing `AbortController` so the
deadline owns both headers and body.

**Tech Stack:** Node.js Fetch/ReadableStream, TextDecoder, Vitest.

## Global Constraints

- The Core API response budget is exactly 8 MiB of raw bytes.
- Connection/deadline failures use `CORE_API_UNAVAILABLE`; response content
  failures use `CORE_API_INVALID_RESPONSE`.
- Public request/result shapes, route status forwarding, and timeout override
  behavior remain unchanged.
- No new dependency, environment variable, or OpenAPI field is introduced.

---

### Task 1: Bounded Response Reader

**Files:**
- Modify: `frontend/server/core-api.test.js`
- Modify: `frontend/server/core-api.js`

**Interfaces:**
- Consumes: Fetch `Response.body`, `Content-Length`, and `AbortSignal`.
- Produces: the existing `request(path, init, options)` result
  `{ status, body }` or an existing `CORE_API_*` error.

- [ ] **Step 1: Write failing overflow tests**

Add tests that return a chunked `ReadableStream` totaling 8 MiB plus one byte
and a response declaring a `Content-Length` above 8 MiB. Require
`CORE_API_INVALID_RESPONSE`, body cancellation, and no complete-body parser.

- [ ] **Step 2: Verify RED**

Run: `npm test -- --run server/core-api.test.js`

Expected: the new requests resolve or consume the oversized body instead of
rejecting at the byte boundary.

- [ ] **Step 3: Implement the minimal reader**

Add `MAX_CORE_API_RESPONSE_BYTES = 8 * 1024 * 1024` and a private async reader
that validates an oversized numeric `Content-Length`, reads `Uint8Array`
chunks, checks the cumulative count before retaining a chunk, cancels on
overflow, concatenates only bounded bytes, decodes with `TextDecoder`, and
calls `JSON.parse()` once.

- [ ] **Step 4: Verify GREEN**

Run: `npm test -- --run server/core-api.test.js`

Expected: all Core API client tests pass, including both overflow paths.

### Task 2: Body Deadline Ownership

**Files:**
- Modify: `frontend/server/core-api.test.js`
- Modify: `frontend/server/core-api.js`

**Interfaces:**
- Consumes: the request's existing effective timeout and internal
  `AbortController`.
- Produces: `CORE_API_UNAVAILABLE` when the deadline expires during body read.

- [ ] **Step 1: Write a failing stalled-body test**

Return response headers immediately, leave its `ReadableStream` pending, and
advance fake timers to the configured deadline. Require the stream to be
cancelled and the request to reject with `CORE_API_UNAVAILABLE`.

- [ ] **Step 2: Verify RED**

Run: `npm test -- --run server/core-api.test.js`

Expected: the request remains pending because the current timer is cleared
after headers.

- [ ] **Step 3: Extend the existing deadline through parsing**

Move `clearTimeout()` to the outer request `finally`, keep a `timedOut` flag,
cancel the active reader on abort, and map deadline expiry to
`CORE_API_UNAVAILABLE` while preserving other parse/read failures as
`CORE_API_INVALID_RESPONSE`.

- [ ] **Step 4: Verify GREEN and compatibility**

Run: `npm test -- --run server/core-api.test.js server.test.js`

Expected: Core API client and Express bridge tests pass with unchanged normal
status/body forwarding and per-request timeout overrides.

### Task 3: Review, Full Verification, and Ledger

**Files:**
- Modify: `AGENTS.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/DEVELOPMENT_GUIDE.md`
- Modify: `docs/reports/PROJECT_ANALYSIS.md`
- Modify: `docs/reports/README.md`
- Create: `docs/reports/AUDIT_REPORT_202.md`

- [ ] **Step 1: Self-review**

Check exact-limit acceptance, raw-byte accounting, cancellation settlement,
timeout cleanup, error precedence, valid response compatibility, and scoped
diff ownership.

- [ ] **Step 2: Run all verification gates**

Run frontend Vitest, typecheck, build, E2E on an available port, Python
aggregate/discovery, compileall, Ruff, required-services local integration,
iteration ledger tests, and `git diff --check`.

- [ ] **Step 3: Update the iteration ledger**

Record only the fresh command counts in Iteration 202 documentation, retain
the newest 10-report navigation window, and verify the ledger parser.
