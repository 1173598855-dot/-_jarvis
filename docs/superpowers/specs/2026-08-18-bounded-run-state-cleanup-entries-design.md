# Bounded Run-State Cleanup Entries Design

## Context

`FileRunStateRepository` validates recovery directories with bounded
`os.scandir()` snapshots, but its optional POSIX cleanup path still calls
`tuple(os.listdir(fd))` for the revisions directory and each flat revision
directory. Both calls preserve descriptor-relative identity safety, but they
materialize an unbounded native list before validating any entry.

## Decision

Use `os.scandir(directory_fd)` as the only cleanup enumerator. Add it to the
safe-cleanup capability check so platforms without descriptor scanning keep
the existing conservative no-cleanup behavior. A private helper collects names
with a caller-owned fixed limit and raises `RunStateIntegrityError` as soon as
the first excess entry is observed.

The revisions directory uses `_MAX_RECOVERY_DIRECTORY_ENTRIES` (`8_192`). A
flat snapshot or staging directory uses `len(_FILE_NAMES)` (`6`), because any
other file set is already ineligible for deletion. Both callers complete their
bounded snapshot before unlinking anything. Overflow and scanner failures are
best-effort cleanup failures: the repository retains data and continues the
already committed save/archive operation.

## Alternatives Rejected

- Checking `len(os.listdir(fd))` is too late because the native list has
  already consumed memory proportional to hostile input.
- Scanning `/proc/self/fd/<fd>` preserves streaming on Linux but introduces a
  procfs dependency and is not a portable POSIX contract.
- Removing revision pruning avoids the allocation but regresses supported
  POSIX lifecycle behavior and leaves stale recovery snapshots indefinitely.

## Safety Invariants

- Never request an entry after the first overflow entry.
- Never delete any revision when the revisions-directory snapshot overflows.
- Never delete any child when a flat-directory snapshot overflows.
- Continue opening directories with `O_DIRECTORY | O_NOFOLLOW` and continue
  rechecking the opened directory identity before each unlink and final rmdir.
- Never close the caller-owned directory descriptor from the scanner helper.
- Do not enable descriptor-relative cleanup unless `os.scandir(fd)` is declared
  by `os.supports_fd` alongside all existing dir-fd operations.

## Verification

Unit tests patch a guarded scanner to prove exact `limit + 1` consumption,
verify a revisions overflow dispatches no directory deletion, and verify a
flat-directory overflow dispatches no unlink/rmdir. Existing POSIX identity
swap tests and Windows conservative-retention tests remain unchanged. Focused
repository tests, aggregate/discovery suites, Ruff, compileall, integration,
frontend checks and ledger validation provide completion evidence.
