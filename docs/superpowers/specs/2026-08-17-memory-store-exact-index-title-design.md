# MemoryStore Exact Index Title Matching Design

**Date:** 2026-08-17
**Iteration:** 167

## Problem

`MemoryStore._update_index_unlocked()` tests `entry.title in content` and then
uses the same substring check for each Markdown row. Writing title `foo` when
`foobar` already exists therefore replaces the `foobar` row even though the
two entries and files are distinct.

## Required Behavior

- A title matches only an index row whose Markdown link label equals that
  complete title.
- A new title that is a prefix, suffix, or substring of another title appends
  its own row without modifying the existing row.
- Rewriting an exact title still replaces its row and does not add a duplicate.
- Directory transaction ownership, file formats, and HTTP response shapes do
  not change.

## Design

Build the exact row prefix `- [<title>](` and scan `MEMORY.md` line by line.
Replace only rows beginning with that prefix. If no exact row was replaced,
append the new row to the existing content. This keeps the current Markdown
format and avoids regular-expression or parser complexity.

## Verification

- Store `foobar`, then `foo`, and require both exact link labels to remain.
- Retain the existing exact-title replacement regression.
- Run MemoryStore, HTTP memory, aggregate, discovery, frontend, integration,
  and repository consistency gates.

## Scope Boundary

This change does not escape Markdown control characters in titles or content,
repair pre-existing malformed index rows, or change entry identity.
