# MemoryStore Probe Deletion Fail-Closed Design

**Date:** 2026-08-17
**Iteration:** 171

## Problem

`MemoryStore.delete_probe()` parses a candidate file before checking its probe
name and cleanup token. A malformed encoded frontmatter value can raise a
known parse exception through the HTTP cleanup path instead of rejecting the
candidate and preserving it.

## Required Behavior

- Unreadable, undecodable, or malformed probe candidates return `False`.
- A rejected candidate remains on disk and its index is not modified.
- Valid integration probes still require the exact memory type, safe entry ID,
  title prefix, and constant-time cleanup-token match before deletion.
- Actual deletion or index-update failures remain visible to callers.
- Public APIs, file formats, locking, and writable/read-only load behavior stay
  unchanged.

## Design

Place only the candidate read and shared frontmatter parse inside the same
known file/metadata exception boundary used by writable legacy loading. Return
`False` for `OSError`, `UnicodeError`, `TypeError`, `ValueError`, or
`OverflowError`. Keep unlinking and index rewriting outside that boundary so a
partial mutation cannot be mistaken for an ordinary rejected candidate.

## Verification

- Add a registered regression with an invalid JSON frontmatter escape.
- Require `delete_probe()` to return `False` without removing the candidate.
- Re-run MemoryStore, aggregate, discovery, warning, frontend, integration,
  compile, lint, and repository consistency gates.

## Scope Boundary

This iteration does not repair malformed files, rewrite legacy frontmatter, or
make deletion/index updates transactional across operating-system failures.
