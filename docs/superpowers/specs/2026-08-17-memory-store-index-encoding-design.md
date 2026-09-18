# MemoryStore Index Encoding Design

**Date:** 2026-08-17
**Iteration:** 168

## Problem

`MemoryStore` interpolates title and the first 100 content characters directly
into one Markdown index row. Newlines can create additional physical rows, and
unescaped square brackets can terminate or nest the link label. A caller can
therefore make `MEMORY.md` describe links that were never created by the store.

## Required Behavior

- Every stored entry contributes exactly one physical index row.
- Carriage returns, line feeds, tabs, C0 controls, NEL, and Unicode line/paragraph
  separators are represented by visible ASCII escape sequences.
- Backslashes and square brackets in link labels are escaped deterministically.
- Exact-title replacement compares the same encoded label that is written.
- Original MemoryEntry titles/content, entry files, IDs, and HTTP shapes remain
  unchanged.

## Design

Add a private `_index_inline(value, escape_label=False)` formatter. It walks the
string once, escapes backslash first, emits `\r`, `\n`, and `\t` for common
controls, emits `\uXXXX` for other line/control characters, and optionally
prefixes `[` and `]` with a backslash. `_update_index_unlocked()` uses the
encoded title in both `index_line` and `index_prefix`, and an encoded view of
the existing 100-character content summary.

This is display encoding only. The entry Markdown body and the in-memory/public
objects retain the caller's original scalar values.

## Verification

- Store a title and content containing newlines plus bracket syntax.
- Require exactly one physical index row and visible escapes in that row.
- Store the same unsafe title again and require exact replacement, not append.
- Run MemoryStore, HTTP memory, aggregate, discovery, frontend, integration,
  and repository consistency gates.

## Scope Boundary

The entry-file frontmatter remains the legacy format and is not converted to a
structured serializer in this iteration. Title/content length limits and index
repair are separate concerns.
