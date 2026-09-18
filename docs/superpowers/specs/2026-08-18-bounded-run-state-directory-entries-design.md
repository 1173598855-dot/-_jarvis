# Bounded Run-State Directory Entries Design

## Context

`FileRunStateRepository` already bounds every recovery file read and the total
authenticated snapshot, but several recovery checks still materialize an
unbounded `Path.iterdir()` result. A damaged or hostile run directory can
therefore consume memory before those file budgets are applied.

## Decision

Add one standard-library `os.scandir()` helper owned by
`FileRunStateRepository`:

- `MAX_RECOVERY_DIRECTORY_ENTRIES` is exactly `8_192` for revision candidates.
- The helper retains at most `limit` direct `Path` entries and raises a stable
  `RunStateIntegrityError` on the first additional entry.
- Scanner and entry errors fail closed as `RunStateIntegrityError`.
- The run root is limited to two entries (`revisions` plus an archive marker),
  unpublished revision probing uses the 8,192 revision-entry budget, and a
  published revision validates no more than its six expected files.

The POSIX descriptor-relative cleanup path remains unchanged in this iteration;
its identity rechecks and existing cleanup tests retain ownership of that
separate race-sensitive contract.

## Error and Compatibility Behavior

An over-budget recovery directory is treated as incomplete or invalid state.
Initial save fails closed rather than guessing which entries to preserve;
unpublished-revision recovery returns `False`; published revision validation
returns the existing integrity error family. Valid empty, exact-budget and
normal archive layouts preserve their prior behavior.

## Testing

The regression suite proves the fixed budget, scanner short-circuit at
`limit + 1`, and rejection of an over-budget unpublished revision directory.
The focused repository suite, aggregate/discovery suites, compileall, Ruff,
integration profile and ledger checks provide the verification gate.
