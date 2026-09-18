# Bounded Worker and Memory Input Reads Implementation Plan

**Goal:** Close the remaining unbounded input paths found during the Iteration
193 audit without changing public response or persistence semantics.

## Task 1: Terminal Worker stdin

- [x] Add a direct `_worker_main()` regression for an oversized JSON request.
- [x] Read at most `WORKER_REQUEST_LIMIT + 1` bytes and reject overflow before
  JSON decoding.
- [x] Preserve the existing failure response and UTF-8 validation behavior.

## Task 2: Writable MemoryStore entries

- [x] Add load and probe-deletion regressions for an oversized candidate.
- [x] Reuse `_read_regular_file()` with an 8 MiB entry budget.
- [x] Confirm oversized candidates are skipped and never unlinked.

## Task 3: Role worker prompt

- [x] Add a protocol regression for an oversized UTF-8 prompt.
- [x] Enforce a 32 KiB byte budget in `WorkerTaskRequest` before process
  serialization.

## Delivery Evidence

- [x] Run affected tests, aggregate suite, full discovery, compileall, Ruff,
  and `git diff --check`.
- [x] Self-review wire fields, exact-limit behavior, failure ordering, and
  existing file/lifecycle semantics.
- [x] Record the required-services integration health-check limitation.
