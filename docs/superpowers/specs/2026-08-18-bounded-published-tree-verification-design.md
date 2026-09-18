# Bounded Published Tree Verification Design

## Context

`FileCapabilityStore._verify_published_content()` used `os.walk()` and then
copied each directory's `directory_names` and `file_names` into tuples before
checking `CapabilityPackageLimits.max_files`. A single directory could
therefore allocate an unbounded child-name list during revision drift checks.

## Decision

- Traverse the published `payload` tree with an explicit LIFO stack of
  directories and `os.scandir()` context managers.
- Count each discovered directory or file before retaining or descending; stop
  with `REVISION_DRIFT` as soon as the configured entry bound is exceeded.
- Close each directory iterator when its scope ends and re-check queued paths
  before opening them, preserving the existing redirect and symlink rejection.
- Keep expected-file hashing, unknown-file detection, and all public error and
  lifecycle contracts unchanged.

## Compatibility

Valid revisions rebuild and retry exactly as before. Drifted payload files,
symlinks, special entries, and entry-count overflow remain fail-closed as
`REVISION_DRIFT` or the existing store-path error.

## Scope Boundary

This iteration does not change archive validation, package limits, revision
state schemas, archive or HTTP inputs, package activation, or OS-level
filesystem/network isolation.
