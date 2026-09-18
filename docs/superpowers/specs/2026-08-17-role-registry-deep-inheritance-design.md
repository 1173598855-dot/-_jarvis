# Role Registry Deep Inheritance Design

**Date:** 2026-08-17
**Iteration:** 179

## Problem

`RoleRegistry._resolve_inheritance()` recursively follows each registered
`parent_role`. A valid acyclic chain longer than Python's recursion limit
raises `RecursionError`, so deep but legitimate role configurations cannot be
read.

## Required Behavior

- Resolve arbitrarily deep acyclic parent chains without consuming Python call
  stack frames.
- Preserve parent-first capability, constraint, and tool de-duplication order.
- Preserve child-over-parent metadata values and the maximum priority rule.
- Preserve `parent_role=None` on fully resolved profiles and the existing
  missing-parent fallback for the deepest unresolved profile.
- Keep cycle rejection, snapshot ownership, sorting, filtering, serialization,
  and public types unchanged.

## Considered Approaches

1. **Iterative chain collection and reverse merge (selected).** Collect the
   profile and its existing parents in a list, copy the deepest base, then
   fold toward the child. This removes recursion without an arbitrary depth
   limit and retains the current merge order.
2. **Reject chains above a fixed depth.** Simple but turns valid configuration
   into a new artificial registration failure.
3. **Catch `RecursionError` during reads.** Produces a bounded error but still
   cannot return valid data and leaves the read path fragile.

## Design

Replace the recursive helper body with an iterative loop. The loop appends the
current profile, follows a registered parent when present, and stops when the
current profile has no parent or its parent is missing. Copy the last profile
as the base, retaining its missing `parent_role` when applicable. Fold the
remaining profiles in reverse order using the existing merge constructor;
every constructed result sets `parent_role=None`, exactly as the recursive
implementation did for resolved children.

Registration already rejects cycles, so no second graph policy is introduced.
Returned profiles remain detached by the existing deep-copy boundaries.

## Verification

- Add a regression that registers a 1100-role chain and asserts the deepest
  result contains both endpoint capabilities and the expected priority.
- Observe the test fail with `RecursionError` before changing production code
  (RED), then pass with the iterative resolver (GREEN).
- Run all RoleRegistry suites, aggregate/discovery, frontend, integration,
  static checks, and ledger guards.

## Scope Boundary

This iteration does not change parent registration policy, introduce a maximum
inheritance depth, alter profile schema validation, or change HTTP routes.
