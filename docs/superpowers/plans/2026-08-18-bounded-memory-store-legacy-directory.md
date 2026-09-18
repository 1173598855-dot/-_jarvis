# Bounded Writable MemoryStore Legacy Directory Entries

**Goal:** Bound writable legacy-memory directory traversal before candidate
parsing while preserving MemoryStore behavior.

## Task 1: Add RED tests

- Assert the fixed 8,192-entry budget through a patched exact-limit directory.
- Assert an over-budget directory returns an empty result without partial
  entries.
- Guard a fake scanner and assert it is advanced only through the first overflow
  entry (`limit + 1`).

## Task 2: Implement the bounded snapshot

- Add `_MEMORY_LEGACY_DIRECTORY_ENTRIES = 8_192`.
- Replace `Path.glob("*.md")` with a context-managed `os.scandir()` helper that
  returns no partial snapshot on overflow or scanner failure.
- Keep candidate parsing, `MEMORY.md` exclusion, regular-file checks and byte
  limits unchanged.

## Task 3: Verify and document

- Run the focused Context Compressor tests, aggregate and discovery suites,
  compileall, Ruff, frontend checks and required-services integration.
- Synchronize the iteration ledger, current analysis, development guide,
  rolling report navigation, and Iteration 209 audit report.
