# MemoryStore Descriptor Read Failure Isolation Design

**Date:** 2026-08-17
**Iteration:** 174

## Problem

`MemoryStore._read_regular_file()` rejects open failures, invalid identity,
oversized files, and invalid UTF-8, but an `OSError` raised by `fstat()` or
`read()` after the descriptor is opened escapes the bounded read-only scan.
One transient or damaged candidate can therefore abort the complete role-tool
memory query instead of preserving valid sibling results.

## Required Behavior

- Post-open descriptor I/O failures reject only the current candidate.
- A valid sibling remains readable after an earlier candidate fails.
- The descriptor is always closed.
- Actual consumed-byte accounting is retained for bounded read-only scans.
- Writable candidate identity checks, parsing rules, scan budgets, locking,
  file formats, and public APIs remain unchanged.

## Design

Keep the existing descriptor-level checks and `finally` close. Add an
`OSError` boundary around opened-descriptor `fstat`, read, and final identity
verification, returning `(None, consumed)`. Callers already skip `None` and
add `consumed` to their total byte budget, so no new public control flow is
needed.

## Verification

- Inject an `os.read` failure for the first of two valid read-only candidates.
- Confirm the old implementation aborts the load (RED), then require the valid
  sibling to be returned (GREEN).
- Re-run MemoryStore, aggregate, discovery, warning, frontend, integration,
  compile, lint, and repository consistency gates.

## Scope Boundary

This iteration does not add retries for storage failures or change how an
`os.close` failure is surfaced.
