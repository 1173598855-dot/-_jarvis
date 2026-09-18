# Terminal Executor Lifecycle Plan

**Date:** 2026-08-17
**Design:** `docs/superpowers/specs/2026-08-17-terminal-executor-lifecycle-design.md`

## Task 1: Reproduce the lifecycle races

- [x] Add a deterministic RED test showing close deletes an in-use sandbox.
- [x] Add a deterministic RED test showing two close waiters can double-clean.
- [x] Verify each failure against the previous implementation.

## Task 2: Implement ownership-safe close

- [x] Add condition-protected execution reservations and closing state.
- [x] Wait for in-flight commands before sandbox cleanup.
- [x] Make concurrent close calls idempotent and preserve non-sandbox behavior.
- [x] Preserve sandbox ownership when cleanup fails so close can retry.
- [x] Include lifecycle regressions in the aggregate suite.

## Task 3: Review and verify

- [x] Run focused lifecycle/terminal tests and aggregate Python suite.
- [x] Run full discovery, compileall, Ruff, frontend tests/build, Playwright,
  required-services integration, and diff checks.
- [x] Update Iteration 155 evidence and the rolling audit window.
- [x] Run final guards for plan completion, report count, temporary paths, and
  listeners.
