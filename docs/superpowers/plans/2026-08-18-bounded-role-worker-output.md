# Bounded Role-Worker Output Plan

## Scope

Replace the Worker result normalizer's unbounded JSON materialization with an
incremental byte-budgeted encoder while preserving protocol behavior.

## Steps

- [x] Inspect `_bounded_json_value()`, its child-process caller, and output-limit
  regressions.
- [x] Add a failing encoder/dumps guard that proves overflow is detected before
  a later chunk or `json.dumps()` call.
- [x] Implement `JSONEncoder.iterencode()` accounting with the existing error.
- [x] Run the role-worker suite, static checks, and self-review.
- [ ] Run aggregate/discovery/frontend/service gates and publish Iteration 191
  evidence.

## Exit Criteria

The Worker result boundary must reject oversized JSON during encoding and keep
all prior normalized values, errors, lifecycle states, and public APIs stable.
