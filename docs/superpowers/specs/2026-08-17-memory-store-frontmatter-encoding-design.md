# MemoryStore Frontmatter Encoding Design

**Date:** 2026-08-17
**Iteration:** 170

## Problem

`MemoryStore.store()` interpolates title, description, parent ID, and probe
token directly into YAML-like frontmatter. Newlines or delimiter-looking text
can create fields and separators that do not represent the original entry.
`_parse_entry()` also splits on any `---` substring, so a stored title or body
can be truncated or misclassified.

## Required Behavior

- Newly stored string frontmatter values round-trip control characters,
  newlines, colons, quotes, backslashes, and delimiter-looking text.
- Legacy unquoted frontmatter remains readable.
- The parser recognizes frontmatter separators as complete physical lines, not
  arbitrary substrings.
- `delete_probe()` uses the same decoded metadata and continues to accept
  existing probe files and tokens.
- Existing body/footer semantics, locking, index encoding, and public APIs stay
  unchanged.

## Design

Encode only string values containing controls, line separators, boundary
whitespace, or quote boundaries with `json.dumps(..., ensure_ascii=False)`;
ordinary values retain the existing unquoted format. Parse documents with `splitlines(keepends=True)`
and locate the first complete `---` delimiter line. Decode quoted JSON strings
and fall back to the existing trimmed scalar representation for legacy fields.
Share the parsed metadata helper between `_parse_entry()` and probe deletion;
known parse failures continue to be skipped by the loader's Iteration 169
boundary.

## Verification

- Add a registered regression storing a title and body containing newlines and
  `---`, then require exact title recovery and an untruncated body prefix.
- Re-run MemoryStore, aggregate, discovery, warning, frontend, integration,
  compile, lint, and repository consistency gates.

## Scope Boundary

The legacy body metadata footer remains part of loaded content for compatibility;
normalizing or repairing existing files is separate work.
