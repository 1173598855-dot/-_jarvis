# Bounded Terminal Process Output Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bound terminal and worker child-process stdout/stderr before the parent retains or decodes untrusted output.

**Architecture:** Add one private concurrent byte-reader helper beside `TerminalExecutor` and reuse it from `TerminalWorker`. The helper keeps a bounded prefix per stream, kills the child on overflow or timeout, and returns status flags; production pipes use the helper while incomplete test doubles use the existing `communicate()` fallback.

**Tech Stack:** Python standard library `subprocess`, `threading`, `io`, UTF-8 decoding, unittest.

## Global Constraints

- TerminalExecutor stdout and stderr budgets are exactly 8 MiB per stream.
- TerminalWorker stdout budget is exactly `WORKER_RESPONSE_LIMIT` (64 KiB); stderr budget is exactly 8 KiB.
- No new dependency, route, environment variable, or public response field is introduced.
- Existing visible output slices, timeout messages, worker protocol fields, and HTTP error envelopes remain unchanged.

---

### Task 1: RED bounded process collector

**Files:**
- Modify: `tests/test_terminal_executor_extended_v2.py`
- Modify: `tests/test_terminal_worker.py`

**Interfaces:**
- Consumes: fake process objects exposing byte `stdout`/`stderr`, `poll`, `wait`, and `kill`.
- Produces: failing regressions proving each stream kills at its first byte beyond its budget and worker oversize is rejected before JSON decode.

- [ ] **Step 1: Write the failing executor overflow test**

Use a fake process whose stdout is `8 * 1024 * 1024 + 1` bytes, whose stderr is empty, and whose `poll()` remains pending until `kill()`. Patch `core.kernel.terminal_executor.subprocess.Popen`, execute an allowed `python` command, and assert `success is False`, the bounded-output diagnostic, and one kill call.

- [ ] **Step 2: Run the focused test to verify RED**

Run: `venv\\Scripts\\python.exe -m unittest tests.test_terminal_executor_extended_v2.TestTerminalExecutorProcessOutput`

Expected: FAIL because the existing implementation calls unbounded `communicate()` and the fake process has no compatible result.

- [ ] **Step 3: Add the worker response overflow regression**

Feed a fake worker process a JSON response whose `stdout` field pushes the encoded wire response beyond `WORKER_RESPONSE_LIMIT`; assert `TerminalWorker.execute()` returns the existing “Worker response exceeds the safety limit” failure and kills the process.

### Task 2: GREEN shared bounded reader

**Files:**
- Modify: `src/core/kernel/terminal_executor.py`
- Modify: `src/core/kernel/terminal_worker.py`

**Interfaces:**
- Consumes: `_bounded_process_communicate(process, timeout, stdout_limit, stderr_limit)`.
- Produces: `(stdout_bytes, stderr_bytes, timed_out, output_limited)` with bounded byte prefixes.

- [ ] **Step 1: Implement concurrent readers**

Read both binary pipes in daemon threads with 8 KiB chunks, count before retaining, set one overflow event at the first over-limit chunk, and poll `process.wait()` in at most 50 ms intervals until exit, timeout, or overflow.

- [ ] **Step 2: Implement cleanup and decode boundaries**

Kill once on timeout/overflow, wait briefly for termination, join readers, return only bounded bytes, and decode with UTF-8 replacement at the caller boundary. Keep the `communicate()` fallback for non-stream test doubles.

- [ ] **Step 3: Wire TerminalExecutor**

Launch with binary pipes, use 8 MiB per-stream limits, preserve timeout/non-zero result fields, and return a bounded-output failure on overflow before applying the existing visible slices.

- [ ] **Step 4: Wire TerminalWorker**

Launch with binary pipes, use `WORKER_RESPONSE_LIMIT`/8 KiB limits, reject overflow before `_decode_result`, and preserve the existing worker timeout and protocol diagnostics.

- [ ] **Step 5: Run focused GREEN tests**

Run: `venv\\Scripts\\python.exe -m unittest tests.test_terminal_executor_extended_v2 tests.test_terminal_worker`

Expected: all focused tests pass, including the new overflow cases and existing timeout/worker lifecycle coverage.

### Task 3: Self-review, full verification, and ledger

**Files:**
- Modify: `AGENTS.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/DEVELOPMENT_GUIDE.md`
- Modify: `docs/reports/PROJECT_ANALYSIS.md`
- Modify: `docs/reports/README.md`
- Create: `docs/reports/AUDIT_REPORT_204.md`

- [ ] **Step 1: Self-review**

Check independent raw-byte accounting, exact-limit success, concurrent pipe draining, kill/timeout races, late events, UTF-8 decoding, visible slice compatibility, and scoped diff ownership.

- [ ] **Step 2: Run all verification gates**

Run focused Python tests, aggregate/discovery, compileall, Ruff, frontend Vitest/typecheck/build, E2E on port 5174, required-services integration, ledger tests, and `git diff --check`.

- [ ] **Step 3: Update the iteration ledger**

Record fresh counts in `AUDIT_REPORT_204.md`, update the rolling window to 195-204, remove only `AUDIT_REPORT_194.md` from navigation, and verify the ledger parser.
