# EventBus Unsubscribe Contract Design

## Context

`EventBus.unsubscribe()` documents `True` only when an ID is found, but always
returns `True`. It also compares arbitrary values directly with integer IDs,
so Python booleans and integral floats can remove unrelated subscriptions.
No production caller consumes the return value.

## Decision

- Accept only exact integer subscription IDs; invalid types return `False`.
- Return `True` only if at least one matching record was removed.
- Keep removal under the existing bus lock.
- Preserve subscriber ordering, callback behavior, and idempotent missing-ID
  handling.

## Verification

A focused regression proves boolean and float values remove nothing, an exact
ID returns true once, and repeated or unknown removal returns false. Existing
pytest expectations are updated from implementation-specific behavior to the
documented contract.
