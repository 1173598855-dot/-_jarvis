# Terminal Worker Lifecycle Design

**Date:** 2026-08-17
**Status:** Approved for implementation

## Context

Both Python HTTP services share one default `TerminalWorker` per application
state. Its `close()` previously removed the owned sandbox immediately, even
while another thread was waiting on a child process, and concurrent close
callers could enter cleanup more than once.

## Decision

- Track validated child-process reservations with a `Condition`.
- Re-check closed/closing state immediately before reserving and launching a
  child.
- Once close begins, reject new reservations and wait for active children to
  finish before cleanup.
- Hold lifecycle ownership through cleanup, publish `_closed` only after
  success, and let one concurrent closer clean the sandbox.
- Preserve the handle and open terminal state when cleanup fails so close can
  retry while new work remains fail-closed.

## Invariants

- A launched child retains its sandbox environment until `communicate()` and
  response handling finish.
- Closing never starts another child and never double-cleans the directory.
- Multiple waiting close callers are idempotent after the first succeeds.
- Wire request/response schema, fixed five operations, output bounds, UID/GID
  handling, and HTTP authorization remain unchanged.

## Verification

Threaded regressions deterministically block child communication and cleanup,
cover immediate and waiting concurrent closers, and verify cleanup retry.
