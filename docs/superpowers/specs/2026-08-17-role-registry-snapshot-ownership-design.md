# Role Registry Snapshot Ownership Design

**Date:** 2026-08-17
**Iteration:** 177

## Problem

`RoleRegistry` stores the caller-owned mutable `AgentProfile` instance and
returns the same instance for parentless `get()` and `list_roles()` results.
Callers can therefore change capabilities, tools, constraints, or nested
metadata without taking the registry lock or going through registration.

## Required Behavior

- Registration detaches the profile and its nested mutable values from the
  caller.
- `get()` and `list_roles()` return detached profiles whose later mutation
  cannot rewrite registry state.
- Inheritance resolution, sorting, filtering, serialization, and public types
  remain unchanged.

## Design

Use `copy.deepcopy()` at the registry ownership boundary: copy the profile when
it is accepted and copy parentless profiles when they leave resolution. Existing
inherited profiles are already newly constructed, so this preserves their
merge semantics while protecting nested metadata in both paths.

## Verification

- Add one regression covering caller mutation, `get()` mutation, nested
  metadata, and `list_roles()` mutation.
- Observe it fail against the current aliasing implementation (RED).
- Apply the two ownership-boundary copies and rerun role registry suites
  (GREEN).
- Run warning, aggregate, discovery, frontend, integration, compile, lint, and
  repository consistency gates.

## Scope Boundary

This iteration does not freeze `AgentProfile`, add a new immutable type, change
inheritance cycle policy, or alter role registration and HTTP schemas.
