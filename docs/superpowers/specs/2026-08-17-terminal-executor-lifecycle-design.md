# Terminal Executor Lifecycle Design

**Date:** 2026-08-17
**Status:** Approved for implementation

## Context

The internal `TerminalExecutor` owns a temporary sandbox directory while
commands execute. Its previous `close()` implementation removed that
directory immediately, even when another thread was still inside `execute()`.
Two concurrent `close()` calls could also race after the first owner cleared
the directory handle.

## Decision

- Track sandbox execution reservations with a `Condition` and an explicit
  closing flag.
- Reserve a concurrency slot atomically before `_run_command()` starts.
- Once closing begins, reject new sandbox commands and wait for all reserved
  commands to release their slots.
- Let exactly one closer clean the directory while holding lifecycle
  ownership, clear the handle only after success, and make later close calls
  idempotent.
- Preserve the existing no-op close behavior for `sandbox=False` executors.

## Invariants

- An in-flight sandbox command keeps its working directory alive until it
  returns, including when close is called from another thread.
- No new sandbox command starts after closing is requested.
- Multiple concurrent close callers never double-clean or dereference a
  cleared directory.
- A cleanup failure preserves the directory handle so a later close can retry.
- The fixed `TerminalWorker` and HTTP default terminal path are unchanged.

## Verification

Regression tests block a real `execute()` call, assert close waits, and run two
concurrent close waiters through the same cleanup path.
