# Terminal Worker Response Protocol Design

**Date:** 2026-08-17
**Iteration:** 152
**Status:** Approved for autonomous implementation

## Context

`TerminalWorker` launches one short-lived child for every fixed read-only
terminal operation. The child output is size bounded, but the parent currently
decodes fields with permissive Python conversions: `bool("false")` becomes
`True`, `int(0.5)` becomes `0`, missing fields receive defaults, unknown fields
are ignored, and child-provided command IDs or risk levels replace the parent
values. Duplicate JSON keys and non-finite numbers are also accepted by the
standard decoder.

That behavior is fail-open at a process trust boundary. A damaged or
compromised child can report a successful result whose types and correlation
do not match the submitted command, and the resulting values enter the parent
audit log. The public HTTP terminal contract and the fixed five-operation
policy do not require any coercion.

## Options Considered

1. **Validate the existing response in the parent.** Parse one exact JSON
   object, reject duplicate keys and non-finite constants, require the complete
   existing field set with exact built-in types, and verify parent-owned
   correlation and result invariants. This is selected because it closes the
   concrete gap without changing the wire shape or public API.
2. **Create a versioned terminal protocol module.** Dedicated immutable request
   and response types would be appropriate if the terminal worker gained a
   persistent multi-message lifecycle. The current worker accepts one small
   request and emits one result, so that abstraction is premature.
3. **Reuse the Plugin Worker protocol.** Its strict JSON helpers are useful as
   a reference, but importing Plugin lifecycle protocol code into the terminal
   boundary would couple unrelated capabilities and error vocabulary.

## Decision

Keep the existing response fields and implement strict decoding inside
`src/core/kernel/terminal_worker.py`:

- require exactly `command_id`, `exit_code`, `stdout`, `stderr`, `duration`,
  `success`, `risk_level`, and `timestamp`;
- reject duplicate keys, JSON constants such as `NaN`/`Infinity`, excessive
  nesting, missing fields, and unknown fields;
- require exact `str`, `int`, and `bool` types rather than coercing values;
- allow `duration` only as a finite, non-negative built-in `int` or `float`;
- require `command_id` and `risk_level` to equal the submitted parent command;
- require `success` to equal whether `exit_code` is zero;
- require `timestamp` to be a non-empty ISO 8601 value accepted by
  `datetime.fromisoformat`;
- retain the existing byte limit and truncate validated stdout/stderr only
  when constructing the local `TerminalResult`;
- convert every protocol rejection into the existing parent-owned failure
  result with the original command ID and risk level.

The child already emits this schema through `asdict(TerminalResult)`, so valid
runtime behavior remains unchanged. No caller receives child stderr or raw
payload content through protocol diagnostics.

## Scope Boundary

- Do not add terminal commands, shell execution, environment inheritance,
  caller cwd overrides, HTTP routes, or execution authority.
- Do not change the child request shape or public `TerminalResult.to_dict()`.
- Do not introduce a new dependency or shared protocol abstraction.
- Do not modify POSIX UID/GID behavior in this iteration.
- Do not stage, commit, reset, clean, or revert the mixed worktree.

## Verification

1. Add parent-decoder regressions for coercion, schema drift, correlation
   mismatch, duplicate keys, non-finite duration, invalid timestamps, and
   inconsistent success/exit state.
2. Run those tests against the current decoder and observe failures because
   malformed responses are accepted.
3. Implement the strict decoder and require focused terminal tests to pass.
4. Run aggregate/discovery, compileall, Ruff, frontend gates, deterministic
   local integration, and diff/temporary-artifact checks.

## Exit Criteria

- Only the exact existing terminal response schema is accepted.
- Malformed responses always become an unsuccessful parent-correlated result.
- A real child operation still succeeds and retains its output.
- Audit entries cannot take a child-supplied command ID or risk classification.
- All project gates pass with fresh Iteration 152 evidence.
