# Bounded Writable MemoryStore Legacy Directory Entries Design

## Context

Writable `MemoryStore._load_legacy()` previously used `Path.glob("*.md")`,
which materialized an unbounded direct-directory traversal before existing
regular-file and entry-byte checks. A hostile or damaged `.auto-memory`
directory could therefore consume memory before those checks were applied.

## Decision

Add a `MemoryStore`-owned `os.scandir()` helper and a fixed
`_MEMORY_LEGACY_DIRECTORY_ENTRIES = 8_192` budget. The helper collects direct
entries incrementally, checks the budget before retaining the first excess
entry, sorts a complete successful snapshot by name, and returns an empty
snapshot for overflow or scanner errors. `_load_legacy()` parses candidates only
after the complete bounded snapshot exists.

## Compatibility

The writable path continues to exclude `MEMORY.md`, reject symlinks/reparse
points and non-regular files, enforce `_MEMORY_ENTRY_MAX_BYTES`, and isolate
known metadata/encoding failures per candidate. Read-only caller-supplied scan
and byte budgets remain unchanged. Exact-budget directories preserve all valid
entries; over-budget directories expose no partial entries to `load()` or
`consolidate()`.

## Testing

Regression tests cover the exact fixed budget, first-overflow rejection without
partial results, and scanner advancement stopping at exactly `limit + 1`.
