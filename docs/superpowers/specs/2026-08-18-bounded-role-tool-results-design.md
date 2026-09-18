# Bounded Role Tool Result Design

## Problem

`RoleToolBroker.invoke()` fully serializes both protocol call arguments and
handler results before comparing them with `RoleToolBudget`. Model-originated
arguments and parent-owned tool results can therefore create large temporary
JSON strings/bytes even though the call will be denied. Result normalization
then creates another UTF-8 string for the replayable invocation record.

## Decision

- Add `bounded_stable_json_size(value, max_bytes)` to the Role Tool protocol
  contract. It computes the exact canonical UTF-8 size incrementally and raises
  `OverflowError` at the first byte beyond the cap.
- Preserve Role Tool's existing JSON type support and error behavior; unlike
  the Plugin Worker contract, do not introduce new depth or integer limits.
- Preflight call arguments against `max_argument_bytes` and handler results
  against `max_result_bytes` before invoking full validation or
  `RoleToolResult.from_value()`.
- Map overflows to the existing `argument_too_large` and `result_too_large`
  denials. Malformed values retain `invalid_arguments`/`invalid_result`.

## Alternatives

1. Keep full serialization before comparison. This preserves behavior but
   leaves the resource allocation gap.
2. Change `RoleToolResult.from_value()` to accept a streaming encoder. That
   would alter the public protocol result API; preflight is smaller and keeps
   successful records byte-for-byte identical.

## Compatibility

Canonical ordering, content strings, byte sizes, handler signatures, budgets,
invocation records, and denial reasons do not change for valid in-budget data.
Only oversized values are rejected before full serialization.

## Verification Contract

Protocol differential tests cover escaped and Unicode values, exact limits,
overflow, and malformed input. Broker tests trace a multi-megabyte handler
result and assert bounded peak allocation plus the existing denial reason.
Targeted, aggregate, full discovery, static, integration, and diff checks must
pass.
