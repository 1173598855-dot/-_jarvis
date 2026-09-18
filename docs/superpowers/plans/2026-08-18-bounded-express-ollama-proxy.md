# Bounded Express Ollama Proxy Implementation Plan

> **For agentic workers:** Execute inline with TDD and review each task before
> continuing.

**Goal:** Bound every Express Ollama upstream response before JSON or stream
parsing while preserving existing client contracts.

**Architecture:** Use one raw-byte-counted non-stream collector and one
cumulative counter in the existing SSE parser. Overflow destroys the upstream
response and routes through current error envelopes.

**Tech Stack:** Node.js HTTP streams, Express, Vitest.

## Global Constraints

- The Express Ollama response budget is exactly 8 MiB.
- Existing status codes, JSON error shapes, SSE error code, and normal frames
  remain unchanged.
- Request body limits and Core API proxy behavior are out of scope.

---

### Task 1: Non-stream Ollama response bound

**Files:**
- Modify: `frontend/server.js`
- Test: `frontend/server.test.js`

**Interfaces:**
- Internal collector counts raw chunk bytes and calls `onOverflow` once.
- Models, chat, and status retain their current caller-specific errors.

- [ ] Extend the Ollama fixture with a controlled >8 MiB chunked response and
  record bytes sent after the proxy closes; run the new test and confirm RED.
- [ ] Implement the bounded collector and wire it into models, chat, and
  status paths.
- [ ] Run the focused server tests and confirm GREEN, including normal success.

### Task 2: Streaming Ollama response bound

**Files:**
- Modify: `frontend/server.js`
- Test: `frontend/server.test.js`

- [ ] Add a fixture stream larger than 8 MiB and assert the proxy emits one
  `OLLAMA_STREAM_ERROR`, no `[DONE]`, and closes upstream early.
- [ ] Add cumulative raw-byte accounting before line splitting and terminate on
  overflow while preserving existing malformed/upstream-error handling.
- [ ] Run the complete frontend server test file and verify GREEN.

### Task 3: Review and verification

**Files:**
- Modify: `AGENTS.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/DEVELOPMENT_GUIDE.md`
- Modify: `docs/reports/PROJECT_ANALYSIS.md`
- Modify: `docs/reports/README.md`
- Create: `docs/reports/AUDIT_REPORT_201.md`

- [ ] Review stream settlement, listener cleanup, byte accounting, and normal
  response compatibility.
- [ ] Run Vitest, typecheck, build, E2E, Python aggregate/discovery, Ruff,
  compileall, local integration, and diff checks.
