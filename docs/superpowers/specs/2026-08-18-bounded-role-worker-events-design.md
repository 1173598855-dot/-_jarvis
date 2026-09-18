# Bounded Role Worker Event Design

## Problem

`RoleWorkerSupervisor._receive_event()` called `Connection.recv_bytes()` without
a maximum size. A child or corrupted transport could therefore allocate an
arbitrarily large event frame before JSON and WorkerEvent validation. Child
results are already bounded by the supervisor's `max_output_bytes`, but the
event envelope adds metadata around that payload.

## Decision

- Define a 64 KiB envelope allowance for task/attempt identifiers, timestamps,
  sequence, kind, and protocol fields.
- The parent requests at most
  `max_output_bytes + MAX_WORKER_EVENT_OVERHEAD_BYTES + 1` bytes from the
  connection. The extra byte is a sentinel; a returned frame beyond the
  calculated limit is ignored before decoding.
- Transport `OSError`/`EOFError` and malformed frames keep the existing
  fail-closed behavior in `_receive_event()`.

## Compatibility

The limit is derived from the configured output budget, so custom valid output
budgets retain their prior envelope capacity. WorkerEvent schema, result
normalization, process lifecycle, terminal status, and history contracts do not
change.

## Verification Contract

Regression tests assert the exact bounded `recv_bytes` request and verify that a
sentinel-overflow frame never reaches `_accept_event`. Existing RoleWorker
lifecycle tests and full aggregate/discovery suites must remain green.
