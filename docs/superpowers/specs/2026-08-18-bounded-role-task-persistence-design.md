# Bounded Role-Task Persistence Design

**Date:** 2026-08-18  
**Stage:** Phase 11 persistence hardening  
**Status:** Delivered in Iteration 190

## Problem

`RoleTaskRecordRepository` stored a JSON snapshot atomically, but recovery used
`Path.read_text()` without a byte ceiling. A damaged or unexpectedly large local
snapshot could therefore allocate the whole file before the existing malformed
record handling ran. The retained Worker output is individually bounded, but a
snapshot contains multiple records and still needs a storage boundary.

## Goals

- Keep one explicit 8 MiB byte budget for a role-task snapshot.
- Reject a file that is already over the budget before opening it.
- Read binary content once with a one-byte sentinel to detect stat-underreported
  growth before UTF-8 decoding or JSON parsing.
- Bound serialization with the same budget and leave the previous file untouched
  when a save is rejected.
- Preserve the existing RLock, atomic temporary-file replacement, malformed-root
  empty-list behavior, and per-record validation semantics.

## Non-Goals

- Changing the Worker protocol, task retention count, output budget, or HTTP
  response shapes.
- Truncating records, resuming Workers, or adding a new persistence format.

## Design

`_read_bounded_bytes()` performs a `stat()` precheck and one `read(limit + 1)` in
binary mode. It raises a local `ValueError` for either pre-open or post-read
overflow; `load()` already treats this as a corrupt snapshot and returns an
empty list. `_encode_bounded_json()` uses `JSONEncoder.iterencode()` and stops
accumulating as soon as the UTF-8 byte budget is exceeded. `_write()` only opens
the temporary path after encoding succeeds, so an oversized save cannot replace
an existing snapshot.

## Acceptance

- Exact-budget snapshots load successfully with a bounded binary read.
- Stat-underreported growth and pre-existing oversized files fail closed without
  opening or parsing the payload.
- Oversized saves raise `ValueError`, clean temporary state, and preserve the
  previous snapshot byte-for-byte.
- Existing round-trip, corruption, orphan recovery, concurrency, and atomic
  replacement tests remain green.
