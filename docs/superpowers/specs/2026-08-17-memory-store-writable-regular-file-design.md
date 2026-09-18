# MemoryStore Writable Regular-File Boundary Design

**Date:** 2026-08-17
**Iteration:** 173

## Problem

The bounded read-only MemoryStore scanner rejects symlink and Windows reparse
entries, but writable `load()` and `delete_probe()` still use path-level
`read_text()`. A link inside the memory directory can therefore expose a valid
Markdown entry outside the configured root through the HTTP list API, or be
accepted and unlinked as a probe candidate.

## Required Behavior

- Writable load and probe deletion accept only regular, non-reparse candidate
  files observed at both `lstat` and opened-descriptor boundaries.
- A symlink to a valid external entry is not loaded.
- A symlink to a valid external probe is rejected and neither the link nor its
  target is removed.
- Writable reads retain the prior universal-newline behavior.
- File formats, directory locking, read-only scan budgets, probe ownership
  checks, and public APIs remain unchanged.

## Design

Reuse the existing descriptor reader, which opens with `O_NOFOLLOW` when the
platform provides it and compares the expected and opened device/inode pair.
Add a writable candidate helper that first `lstat`s the path, rejects
non-regular or reparse entries, reads only the observed byte count, and treats
known OS failures as an absent candidate. Normalize CRLF and CR to LF after
decoding to preserve the former `Path.read_text()` semantics. Route writable
legacy loading and probe parsing through that helper.

## Verification

- Add real symlink regressions for writable load and probe deletion.
- Confirm both old paths follow the external target (RED), then require
  fail-closed rejection and retained files (GREEN).
- Re-run MemoryStore, aggregate, discovery, warning, frontend, integration,
  compile, lint, and repository consistency gates.

## Scope Boundary

This does not make path unlink and index rewrite one atomic OS transaction or
attempt to distinguish hard links from ordinary regular files.
