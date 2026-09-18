# Bounded MemoryStore Index Reads Design

**Date:** 2026-08-18
**Iteration:** 192

## Problem

Writable `MemoryStore` mutations read `MEMORY.md` with `Path.read_text()` while
holding the directory transaction. A damaged or externally replaced index can
therefore allocate without a byte ceiling. Probe deletion also removed the
candidate file before discovering that the index could not be read.

## Required Behavior

- Bound every writable index read to 8 MiB before decoding and splitting lines.
- Reuse the existing regular-file, reparse-point, descriptor identity, and
  post-open size checks.
- Reject existing redirecting or dangling `MEMORY.md` links before creation;
  create a missing index exclusively.
- Read and validate the index before writing a new entry file.
- Read and validate the index before deleting a probe candidate; an invalid or
  oversized index leaves the candidate untouched.
- Preserve index row replacement, append behavior, newline normalization,
  process locking, and public MemoryStore/HTTP contracts.

## Approach

Add one `_read_index_unlocked()` helper with the fixed index budget. `store()`
obtains one bounded snapshot and passes it to the index updater, avoiding a
second read. `delete_probe()` obtains the snapshot before `unlink()` and fails
closed if it cannot be loaded.

## Scope Boundary

This iteration does not cap individual memory entry files, change read-only
load budgets, alter index formatting, or add filesystem/network isolation.
