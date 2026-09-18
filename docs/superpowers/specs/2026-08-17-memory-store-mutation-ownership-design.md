# MemoryStore Mutation Ownership Design

## Context

Each Python service shares one writable `MemoryStore`. `store()` writes an
entry file and then performs a read/append-or-rewrite of `MEMORY.md` without
synchronization. Concurrent writes of the same title can both observe the
title as absent and append duplicate index rows. Readers can also scan while a
write transaction is incomplete.

## Decision

- Give each writable MemoryStore one reentrant mutation lock.
- Serialize complete store and probe-delete transactions.
- Serialize legacy writable loads with mutations so callers do not parse a
  partially written entry.
- Keep read-only bounded scanning unchanged.
- Let consolidate hold the same reentrant lock across its load/compress/store
  sequence.
- Preserve file formats, entry IDs, index replacement rules, and HTTP shapes.

## Verification

A deterministic delayed index read lets two same-title writes observe the
same pre-update index in the old implementation. The fixed implementation must
retain both entry files while exposing exactly one index row for that title.
Existing concurrent store/load suites protect broader behavior.
