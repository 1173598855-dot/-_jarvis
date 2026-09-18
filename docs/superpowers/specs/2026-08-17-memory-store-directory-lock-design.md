# MemoryStore Directory Transaction Ownership Design

**Date:** 2026-08-17
**Iteration:** 166

## Problem

Iteration 165 serialized mutations made through one `MemoryStore` instance.
The service can still construct more than one writable instance for the same
directory, and separate processes can do the same. Their independent locks
allow both writers to read the same `MEMORY.md` snapshot and then append or
rewrite it, leaving a valid entry file without its index row.

## Goals

- Serialize writable transactions for every cooperating `MemoryStore` that
  resolves to the same directory.
- Cover separate instances in one process and spawned service processes.
- Keep store, probe deletion, writable load, and consolidate coherent with the
  entry/index transaction defined in Iteration 165.
- Preserve the public API, Markdown formats, and lock-free bounded read-only
  scan path.

## Design

Each canonical memory directory maps to one weakly retained process-local
`threading.RLock`. The lock prevents separate instances in one process from
entering the directory transaction concurrently without retaining abandoned
temporary-directory keys forever.

The process-local lock wraps one operating-system lock:

- Windows uses a named mutex derived from the SHA-256 digest of the normalized
  canonical directory path. An abandoned mutex is treated as acquired so a
  replacement service can recover.
- POSIX opens `.memory-store.lock` with `O_NOFOLLOW` where available, verifies
  that it is a regular file, and holds `flock(LOCK_EX)` for the transaction.

Public writable operations acquire `_mutation_transaction()` exactly once.
Nested implementation work uses `_ensure_index_unlocked()`,
`_update_index_unlocked()`, `_store_unlocked()`, and `_load_legacy()` so it
does not reacquire a non-reentrant OS primitive. `consolidate()` holds the
directory transaction across its load, compression, and rewrite sequence.

## Failure Behavior

OS mutex or lock-file creation, acquisition, release, and close failures remain
explicit `OSError` failures. The implementation does not continue with an
unlocked write after coordination fails.

## Verification

- Force two independent in-process instances to pause after reading the same
  index; both distinct index rows must survive.
- Repeat the schedule with two real `spawn` processes; before the fix one row
  is lost, while the directory transaction keeps both.
- Re-run all MemoryStore, HTTP memory, aggregate, discovery, frontend, and
  required-services integration gates.

## Scope Boundary

This change coordinates cooperating `MemoryStore` writers. It does not make
individual Markdown writes crash-durable with temporary files and directory
`fsync`, prevent unrelated processes from editing the files directly, or add
locks to the bounded read-only role-tool scanner.
