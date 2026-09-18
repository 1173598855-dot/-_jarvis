# Bounded Express Git Output Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bound Express Git child-process output before retaining or decoding
it while preserving the existing read-only route contracts.

**Architecture:** Keep `runGitCommand()` in `frontend/server.js`, add an
optional injected spawn function for direct unit coverage, and collect bounded
Buffer chunks. A shared single-shot overflow path destroys streams and kills
the child before rejecting; route handlers continue mapping all failures to
`GIT_COMMAND_FAILED`.

**Tech Stack:** Node.js child_process streams, Buffer, Vitest.

## Global Constraints

- The per-stream Git output budget is exactly 8 MiB of raw bytes.
- Overflow must reject and terminate the child before any full output string is
  constructed.
- Existing Git route paths, arguments, success shapes, and error envelopes are
  unchanged.
- No new dependency, environment variable, or OpenAPI field is introduced.

---

### Task 1: RED Git Output Boundary

**Files:**
- Modify: `frontend/server.test.js`

**Interfaces:**
- Consumes: a fake child process with EventEmitter stdout/stderr and `kill()`.
- Produces: a failing assertion for exported `runGitCommand()` overflow.

- [ ] **Step 1: Write the failing unit test**

Import `runGitCommand`, inject a fake `spawnImpl`, emit one 8 MiB stdout
Buffer followed by one byte, and require rejection with
`code: 'GIT_OUTPUT_TOO_LARGE'` plus one child `kill()` call.

- [ ] **Step 2: Verify RED**

Run: `npm test -- --run server.test.js`

Expected: the current helper resolves after `close` because it has no output
budget or exported test seam.

### Task 2: GREEN Bounded Collector

**Files:**
- Modify: `frontend/server.js`
- Modify: `frontend/server.test.js`

**Interfaces:**
- Consumes: `runGitCommand(args, { command, cwd, spawnImpl })`.
- Produces: `{ stdout, stderr }` decoded only after bounded successful close;
  overflow rejects with internal `GIT_OUTPUT_TOO_LARGE`.

- [ ] **Step 1: Add the minimal implementation**

Introduce `MAX_GIT_OUTPUT_BYTES = 8 * 1024 * 1024`, count each Buffer chunk
before pushing it, and use a single settlement guard. On overflow, reject,
destroy both streams when present, and call `git.kill()`; on close, concatenate
bounded Buffers and decode as UTF-8.

- [ ] **Step 2: Verify GREEN**

Run: `npm test -- --run server.test.js`

Expected: the overflow unit test and all existing Git route tests pass.

- [ ] **Step 3: Add the late-event regression**

Emit child `error` and `close` after the overflow and assert the rejection is
still observed once; keep `kill()` idempotent through the settlement guard.

### Task 3: Review, Full Verification, and Ledger

**Files:**
- Modify: `AGENTS.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/DEVELOPMENT_GUIDE.md`
- Modify: `docs/reports/PROJECT_ANALYSIS.md`
- Modify: `docs/reports/README.md`
- Create: `docs/reports/AUDIT_REPORT_203.md`

- [ ] **Step 1: Self-review**

Check raw-byte accounting, child termination, single settlement, UTF-8
decoding, exact-limit success, route error mapping, and scoped diff ownership.

- [ ] **Step 2: Run all verification gates**

Run the focused and full Vitest suites, typecheck, build, E2E on an available
port, Python aggregate/discovery, compileall, Ruff, required-services local
integration, ledger tests, and `git diff --check`.

- [ ] **Step 3: Update the iteration ledger**

Record fresh counts, update the rolling window to 194-203, and verify the
ledger parser against `AUDIT_REPORT_203.md`.
