# Bounded Capability Registry collections Design

**Date:** 2026-08-18
**Iteration:** 185

## Problem

Capability Registry discovery enforced `_MAX_CHILDREN` and `_MAX_FILES` only
after materializing all direct children or all tree files in a list. A large
repository-local directory or capability tree could therefore consume memory
proportional to untrusted entry count before the existing count error was
reported.

## Required Behavior

- Direct-child selection must retain at most `_MAX_CHILDREN` candidates while
  still counting every entry and returning the same deterministic first names.
- Tree file selection must retain at most `_MAX_FILES` candidates while still
  counting every eligible file and preserving the existing `tree_file_limit`
  and `symlink_rejected` precedence.
- Existing ignored-path, symlink, ordering, digest, metadata, and public record
  behavior must remain unchanged for bounded trees.
- A shared collector must make the bounded-memory invariant directly testable.

## Approach

Use a module-local `_bounded_sorted()` helper backed by `heapq.nsmallest()`. It
wraps the source iterator with a scalar counter, retains only the requested
selection window, and returns both the sorted selection and total count. Child
and tree discovery use the helper before applying the existing limit issue or
validation.

## Scope Boundary

The collector does not change file-content byte limits, close same-user path
replacement races, archive/HTTP inputs, Plugin execution, or OS-level
filesystem/network isolation.
