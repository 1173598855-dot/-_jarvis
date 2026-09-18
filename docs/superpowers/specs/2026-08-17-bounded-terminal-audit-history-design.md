# Bounded Terminal Audit History Design

**Date:** 2026-08-17
**Iteration:** 157

## Problem

`TerminalExecutor` and the service-default `TerminalWorker` retain audit
records in unbounded lists. A long-lived service can therefore grow memory in
proportion to terminal requests. The existing Worker test named
`test_worker_keeps_a_bounded_audit_log` writes only one entry and does not
exercise retention. Both getters also return the original mutable dictionaries,
so a caller can rewrite stored evidence through a returned snapshot.

## Decision

Both implementations will use a `deque` with the shared fixed capacity
`TERMINAL_AUDIT_LIMIT = 1000`. Each implementation owns a dedicated audit lock
covering append, snapshot, and clear operations. This follows the existing
bounded history pattern used by the role-tool broker while keeping terminal
lifecycle locking independent from audit readers.

The public methods remain `get_audit_log(limit: int = 100)` and
`clear_audit_log()`. A positive limit returns at most the newest requested
records, a zero limit returns an empty list, and a negative or non-plain-integer
limit raises `ValueError`. Returned entries are shallow dictionary copies;
terminal audit values are scalars, so this prevents callers from mutating the
stored record.

## Behavioral Scope

- Preserve the existing record schema and newest-first window semantics.
- Preserve which execution paths are audited; this iteration does not start
  recording policy rejections that were previously omitted.
- Evict only the oldest record after the fixed capacity is reached.
- Apply the same bound to the legacy in-process executor and default process
  Worker.
- Do not change terminal commands, risk assessment, process isolation,
  response validation, HTTP schemas, or Plugin API history.

## Alternatives Considered

1. Truncate only in `get_audit_log()`. Rejected because stored memory remains
   unbounded.
2. Keep lists and delete the oldest element after every full append. Rejected
   because each append moves the retained list and duplicates concurrency
   bookkeeping.
3. Use fixed-capacity deques with locks. Selected because append and eviction
   remain O(1), the retention invariant is structural, and snapshots are easy
   to protect.

## Verification

TDD regressions will first demonstrate that each implementation retains more
than 1000 records and exposes mutable entries. Focused tests will then prove
oldest-entry eviction, newest-entry retention, zero/invalid limit behavior,
copy isolation, and clear behavior. Completion requires the canonical Python
aggregate and discovery suites plus compileall, Ruff, Vitest, Playwright,
typecheck, build, required-services integration, and diff/ledger guards.
