# Bounded Capability tree traversal Design

**Date:** 2026-08-18
**Iteration:** 186

## Problem

After candidate-list bounding, Capability Registry tree hashing still used
`Path.rglob("*")` without a directory-entry budget. A tree containing mostly
directories, or a path deeper than the platform's normal recursion comfort,
could consume unbounded traversal work before the file-count limit applied.

## Required Behavior

- Traverse repository capability trees iteratively with a fixed non-ignored
  entry budget.
- Preserve ignored-part pruning, symlink rejection, deterministic relative
  file selection, content hashing, and `tree_file_limit` behavior.
- Close each directory enumerator promptly and avoid recursive Python calls or
  a full tree-entry list.
- Keep existing stable trees and public records unchanged.

## Approach

Replace `rglob()` with an explicit `os.scandir()` stack. The walker counts each
non-ignored entry, rejects a non-ignored symlink, pushes real directories, and
emits regular files into the existing `_bounded_sorted()` collector. The
`_MAX_TREE_ENTRIES` budget is intentionally above the existing file/child
limits to avoid changing ordinary capability trees while failing closed on
directory-only explosions.

## Scope Boundary

This does not add archive/HTTP inputs, change same-user path replacement trust,
alter file-content byte limits, or provide OS-level filesystem/network
isolation.
