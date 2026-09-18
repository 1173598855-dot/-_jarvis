# MemoryStore Entry Target Boundary Design

**Date:** 2026-08-18
**Iteration:** 193

## Problem

`MemoryStore.store()` derives a deterministic entry filename but writes it with
`Path.write_text()` without checking the existing filesystem object. A
pre-created symlink can redirect the serialized memory body outside the memory
directory.

## Required Behavior

- Before serializing or writing, accept only a missing or regular,
  non-reparse entry target.
- Reject symlink, reparse-point, directory, and other non-regular targets with
  a bounded `OSError`.
- Leave the target and any external link destination unchanged on rejection.
- Preserve normal replacement of an existing regular entry, index updates,
  directory/process locking, and public MemoryStore/HTTP behavior.

## Approach

Add a small `lstat()` preflight for the deterministic entry path and reuse the
existing reparse-point predicate. The check runs before body construction and
before the bounded index snapshot; no new public API or storage format is
introduced.

## Scope Boundary

This does not change hard-link semantics, make index rewrites atomic, cap entry
body size, or provide OS-level filesystem/network isolation.
