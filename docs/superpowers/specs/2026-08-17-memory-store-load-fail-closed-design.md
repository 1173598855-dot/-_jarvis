# MemoryStore Writable Load Fail-Closed Design

**Date:** 2026-08-17
**Iteration:** 169

## Problem

Writable `MemoryStore.load()` parses legacy Markdown entries under its
transaction lock, but malformed frontmatter can raise `ValueError`,
`OverflowError`, or decoding/file errors and abort the whole load. The
read-only bounded scanner already skips invalid candidates, so the two load
paths expose inconsistent resilience to one damaged file.

## Required Behavior

- A damaged or unreadable entry file is skipped without aborting writable load.
- Valid sibling entries remain loadable in deterministic directory order.
- Existing `MemoryEntry` parsing, filtering, locking, and public APIs remain
  unchanged.
- Unexpected programming errors are not hidden by a blanket exception catch.

## Design

Wrap only the legacy file read and `_parse_entry()` call in
`_load_legacy()` with the known file/metadata exception set already handled by
the bounded read-only path: `OSError`, `UnicodeError`, `TypeError`,
`ValueError`, and `OverflowError`. Continue to the next file on those errors;
append only successfully parsed entries.

## Verification

- Add a registered writable-load regression with one malformed integer and one
  valid entry, requiring the valid entry to survive.
- Run the complete MemoryStore class, Python aggregate/discovery, compileall,
  Ruff, frontend, integration, and repository consistency gates.

## Scope Boundary

Frontmatter value encoding and repair of already-corrupt files remain separate
format-hardening work.
