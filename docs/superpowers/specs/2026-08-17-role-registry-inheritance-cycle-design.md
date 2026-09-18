# Role Registry Inheritance Cycle Design

**Date:** 2026-08-17
**Iteration:** 178

## Problem

`RoleRegistry.register()` accepts profiles that complete an inheritance cycle.
Later `get()` and `list_roles()` calls recursively resolve that invalid graph
until Python raises `RecursionError`, so one bad registration can make normal
registry reads unavailable.

## Required Behavior

- Reject a profile that directly or indirectly makes its own name reachable
  through registered `parent_role` links.
- Perform cycle validation and insertion under the same registry lock so a
  concurrent registration cannot invalidate the decision.
- Leave the registry unchanged after rejection.
- Continue to allow a profile whose parent is not registered yet; forward
  references retain the existing parentless fallback until that parent exists.
- Preserve duplicate-name error precedence, inheritance merge order, snapshot
  ownership, serialization, and public types.

## Considered Approaches

1. **Validate the candidate parent chain during registration (selected).**
   Iteratively follow registered parents from the candidate and reject when the
   candidate name is reached. This keeps the graph valid at its write boundary
   and avoids recursion in the validator.
2. **Track visited roles only during resolution.** This bounds the failure but
   leaves an invalid record stored, allowing every future read to fail.
3. **Validate the full graph on every read.** This detects corruption but adds
   unnecessary repeated work and still accepts invalid state.

## Design

Add a private `_validate_acyclic_registration(profile)` helper that is called
inside the existing `register()` critical section after the duplicate check and
before insertion. Start the path with the candidate name, follow its parent
through `_roles`, and raise a deterministic `ValueError` containing the closed
cycle path if a visited name is encountered. Stop at `None` or an unregistered
parent so forward references remain compatible.

The current public registration path is the only writer to `_roles`; therefore
maintaining this invariant there is sufficient for recursive inheritance
resolution to remain safe without changing its merge behavior.

## Verification

- Add registered regressions for a direct self-cycle and a two-role cycle.
- Assert the multi-role rejection leaves the earlier forward reference intact
  and the rejected role absent.
- Confirm the tests fail with the current implementation before production
  code changes (RED), then pass after the minimal validator (GREEN).
- Re-run all role-registry tests, the canonical aggregate suite, full discovery,
  Ruff, compileall, ledger checks, and `git diff --check`.

## Scope Boundary

This iteration does not require parents to exist at registration time, add
general profile schema validation, change unregister behavior, replace recursive
inheritance merging, or expose new HTTP/API fields.
