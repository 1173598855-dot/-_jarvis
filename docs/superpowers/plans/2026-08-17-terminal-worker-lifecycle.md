# Terminal Worker Lifecycle Plan

**Date:** 2026-08-17
**Design:** `docs/superpowers/specs/2026-08-17-terminal-worker-lifecycle-design.md`

## Task 1: Reproduce worker lifecycle races

- [x] RED: close completes while a child communication is in flight.
- [x] RED: two immediate close callers enter cleanup twice.
- [x] RED: two close waiters double-clean after an active child exits.

## Task 2: Implement parent-owned lifecycle

- [x] Add condition-protected closing state and child reservations.
- [x] Re-check closing state before process launch.
- [x] Wait for active children and make close cleanup single-owner.
- [x] Preserve cleanup-failure retry and warning-free test ownership.

## Task 3: Review and verify

- [x] Run focused terminal tests and aggregate Python suite.
- [x] Run full discovery, compileall, Ruff, frontend tests/build, Playwright,
  required-services integration, and diff checks.
- [x] Update Iteration 156 evidence and rolling report window.
- [x] Run final plan, report, scratch-directory, listener, and Git guards.
