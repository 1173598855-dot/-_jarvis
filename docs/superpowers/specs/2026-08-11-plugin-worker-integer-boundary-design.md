# Plugin Worker Integer Boundary Design

**Date:** 2026-08-11

## Context

The V1 Plugin Worker protocol already bounds wire-line length, JSON nesting,
and malformed JSON decoding. A direct Python caller can still construct a
protocol record whose JSON payload contains an arbitrarily large `int`.
`_require_json()` accepts that value, then `stable_json_bytes()` reaches
`json.dumps()`, where Python may raise its environment-dependent integer-string
limit as a raw `ValueError`. This breaks the protocol's stable,
`PluginWorkerProtocolError` failure boundary.

## Alternatives considered

1. Catch `ValueError` only around `json.dumps()`. This is small, but permits
   invalid records to be constructed and leaves validation dependent on the
   interpreter's configuration.
2. **Recommended: enforce one conservative decimal-integer limit in protocol
   validation.** `_require_json()` rejects oversized JSON values before freezing
   them, and `_require_positive_integer()` applies the same bound to protocol
   numeric fields. Serialization then sees only bounded values.
3. Add a separate parent-runtime serialization guard. This duplicates protocol
   validation and would leave direct helpers and future runtimes inconsistent.

## Design

Introduce a public `MAX_PLUGIN_WORKER_INTEGER_DIGITS = 512` constant and an
internal magnitude threshold of `10 ** 512`. JSON integers with an absolute
magnitude greater than or equal to that threshold are rejected. The exact
comparison avoids converting attacker-provided integers to decimal text and
therefore remains safe even when Python's own conversion limit differs by
environment.

The bound is applied at the two protocol validation entry points:

- `_require_json()` validates Broker arguments/results and lifecycle audit data.
- `_require_positive_integer()` validates `pid` and `generation` fields.

All failures use the existing `PluginWorkerProtocolError` with bounded,
non-secret diagnostic text. V1 fields, message kinds, canonical JSON order,
line-size limits, Broker behavior, Worker ownership, HTTP routes, and manifest
permissions remain unchanged.

## Data and error flow

`PluginBrokerRequest(...)` -> `_require_json(arguments)` -> integer magnitude
check -> immutable record -> `encode_message()` -> `stable_json_bytes()`.

Oversized direct integers now stop at validation rather than reaching
`json.dumps()`. Generic callers of `stable_json_bytes()` receive the same
protocol error. A 512-digit magnitude remains serializable and round-trips
through the canonical V1 wire format.

## Test strategy and acceptance criteria

1. Add a focused protocol regression that first fails because the current code
   leaks `ValueError` for `10 ** 512`.
2. Verify the same oversized value is rejected by both `stable_json_bytes()`
   and direct `PluginBrokerRequest` construction as `PluginWorkerProtocolError`.
3. Verify an in-limit 512-digit integer still round-trips through
   `encode_message()` and `decode_message()`.
4. Run the focused protocol suite, plugin Worker suites, aggregate Python
   suite, full discovery, compilation, frontend tests, typecheck, build, and
   deterministic local integration.

## Scope and recovery

This is a protocol resource-boundary correction only. It does not introduce a
new Broker capability, Plugin permission, network/file authority, dependency,
HTTP API, or OS sandbox. Recovery is a normal revert of the small protocol and
test changes if a documented Plugin legitimately needs a number outside the
512-digit safety budget.

## Self-review

- The chosen boundary is below Python's minimum configurable nonzero
  integer-string threshold, so validated values do not rely on the host's
  default 4,300-digit setting.
- The direct-construction and generic-serialization paths share the same
  validation rule.
- The change is backward compatible for ordinary protocol values and does not
  change V1 schemas or HTTP contracts.
