# Plugin API Audit Ownership Design

**Date:** 2026-08-17
**Iteration:** 158

## Problem

`XiaoYiPluginAPI` appends every access entry to an unbounded list. It then
passes the same mutable dictionary to the Worker-owned audit sink and returns
that same dictionary from `get_audit_log()`. Plugin code can therefore mutate a
snapshot and rewrite both the API's stored record and the audit evidence later
returned to the parent in `PluginLifecycleResult`. Repeated denied Broker calls
are logged before the Broker decision, so the 32-call Broker budget does not
bound the API's local memory use.

## Decision

The API will retain the newest `PLUGIN_API_AUDIT_LIMIT = 1000` entries in a
fixed-capacity `deque`. A dedicated lock will cover append and snapshot. The
audit sink will be called after releasing that lock and will receive a copied
dictionary; getters will also return fresh dictionary copies.

`get_audit_log(limit: int = 100)` will match the terminal audit contract: only
an exact non-negative integer is accepted, zero returns an empty list, and
invalid values raise `ValueError`. Audit entries contain scalar string values,
so one shallow copy per ownership boundary is sufficient.

## Data Flow

1. `log_access()` builds one bounded scalar entry.
2. Under the audit lock, the API appends that entry; deque capacity evicts the
   oldest record when necessary.
3. After releasing the lock, the API passes `entry.copy()` to the trusted
   Worker sink. Sink re-entry cannot deadlock the API.
4. `get_audit_log()` validates the requested limit and copies the selected
   entries under the same lock.

## Alternatives Considered

1. Rely on the Worker/Broker budgets. Rejected because API logging occurs
   before every Broker result and plugin code can continue after denials.
2. Remove local history and stream only to the sink. Rejected because it breaks
   the existing plugin-facing getter.
3. Use a bounded deque with separate copies for storage, sink, and getters.
   Selected because it preserves the API while making retention and ownership
   explicit.

## Scope

- Preserve entry fields, 200-character argument text, permission behavior,
  Broker calls, sink exception propagation, and the Worker's 100-entry wire
  audit limit.
- Do not change Plugin Broker audit records, protocol schemas, lifecycle
  status, or HTTP endpoints.
- Do not add persistence or expose a clear operation.

## Verification

TDD will prove the current 1005-entry retention and two-way aliasing before
production edits. Focused tests will then cover eviction order, getter
isolation, sink isolation, exact limit validation, and existing Plugin API
operations. Completion requires canonical aggregate/discovery suites and the
full repository verification matrix.
