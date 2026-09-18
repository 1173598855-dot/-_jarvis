# Bounded Plugin Broker Result Design

## Problem

`PluginBrokerSession.handle()` serializes a parent-owned capability handler's
complete result with `stable_json_bytes()` before comparing it with the
65,536-byte lifecycle exchange budget. Plugin requests are already bounded by
the Worker protocol line limit, but handler results do not cross that boundary
before this check. A faulty handler can therefore cause proportional temporary
string and byte allocations even though the result is ultimately denied.

## Decision

- Add `bounded_stable_json_size(value, max_bytes)` to the Plugin Worker
  protocol contract. It validates the same supported JSON types and computes
  the exact canonical UTF-8 size without constructing the serialized value.
- Count JSON string escapes and UTF-8 widths incrementally. Stop at the first
  byte beyond `max_bytes` and raise `OverflowError`.
- Use the helper only for capability handler results. Existing request and
  event-payload sizing remain unchanged because decoded requests have already
  passed the 65,536-byte Worker frame boundary.
- Preserve `handler_result_invalid` for malformed in-budget results and
  `result_too_large` for budget overflow. Never construct or stage an event
  after either denial.

## Alternatives

1. Keep full serialization and compare afterward. This preserves the current
   implementation but does not enforce the resource boundary before allocation.
2. Introduce a streaming handler-result API. This could bound producer memory
   too, but changes the handler contract and is unnecessary for the current V1
   event capability.

The incremental exact-size helper is the smallest contract-preserving change.

## Compatibility

Canonical wire encoding, protocol schemas, handler signatures, lifecycle
exchange accounting, audit entries, and successful result objects do not
change. Exact-limit results remain accepted; only the temporary allocation
behavior of oversized handler results changes.

## Verification Contract

Protocol tests compare bounded sizes with `stable_json_bytes()` across nested,
escaped, and Unicode values and assert exact-limit/overflow behavior. A Broker
regression uses allocation tracing to prove an oversized handler result is
denied without a proportional serialization copy. Targeted, aggregate, full
discovery, Ruff, compileall, local integration, and diff checks must pass.
