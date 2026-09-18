# MemoryStore Unicode Frontmatter Line Separator Design

**Date:** 2026-08-17
**Iteration:** 172

## Problem

MemoryStore frontmatter marks NEL (`U+0085`) and Unicode line/paragraph
separators (`U+2028`, `U+2029`) as unsafe, but `json.dumps(...,
ensure_ascii=False)` leaves those characters literal. Python's
`splitlines(keepends=True)` then treats them as physical line boundaries, so a
quoted frontmatter value can be truncated and no longer round-trip.

## Required Behavior

- Newly stored frontmatter strings containing NEL, U+2028, or U+2029 round-trip
  exactly through `MemoryStore.load()`.
- JSON encoding remains Unicode-preserving for ordinary non-ASCII characters.
- Legacy unquoted values, ASCII controls, newline handling, delimiter parsing,
  index rows, locking, and public APIs remain unchanged.

## Design

After JSON-encoding an unsafe frontmatter string with `ensure_ascii=False`,
translate only the three Unicode separators recognized by `str.splitlines()`
to JSON `\\u....` escapes. The existing decoder's `json.loads()` restores the
original scalar after the physical frontmatter lines have been parsed.

## Verification

- Add a registered regression containing all three Unicode separators in a
  stored title.
- Confirm the old implementation truncates the title (RED), then require exact
  round-trip recovery (GREEN).
- Re-run MemoryStore, aggregate, discovery, warning, frontend, integration,
  compile, lint, and repository consistency gates.

## Scope Boundary

This change does not alter body normalization, legacy file migration, or the
frontmatter grammar beyond preserving encoded scalar line boundaries.
