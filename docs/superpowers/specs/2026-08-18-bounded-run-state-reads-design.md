# Bounded Run State reads Design

**Date:** 2026-08-18
**Iteration:** 187

## Problem

`FileRunStateRepository` read the active manifest, six revision files, and an
optional archive with `read_text()`/`read_bytes()` before any size check. The
authenticated loader retained all six decoded byte strings at once, so a
replaced local recovery file could force unbounded allocation.

## Required Behavior

- Every recovery file read must perform a stat precheck and one bounded binary
  read with a sentinel byte.
- No single recovery file may exceed 8 MiB, and the six-file authenticated
  snapshot may not exceed 32 MiB in total.
- Active manifest, revision verification, archive comparison, and atomic
  read-back must use the same bounded path and preserve existing integrity
  errors.
- Stable saved states, HMAC verification, revision recovery, archive behavior,
  and public `StoredRunState` values remain unchanged.

## Approach

Add one module-local `_read_bounded_bytes()` helper with a caller label. Route
manifest JSON, revision files, archive bytes, revision verification, and
atomic read-back through it. Count actual loaded bytes before decoding and
reject a snapshot that exceeds the aggregate budget.

## Scope Boundary

This does not change RunState schema validation, event retention policy,
filesystem ownership/locking, HMAC algorithms, or OS-level isolation.
