# Ruff Helper Module Fallback Design

## Context

The local Ruff helper only considered a `ruff` executable discoverable through
`PATH`. A project virtual environment can contain Ruff as an importable module
while its `Scripts` directory is not activated, causing the helper to report
`ruff_available: false` even though the documented Python environment can run
Ruff.

## Decision

Resolve the command in this order:

1. use the `ruff` executable found by `shutil.which`;
2. otherwise invoke `[sys.executable, "-m", "ruff"]`;
3. retain a final `ruff` command fallback for an unusual interpreter without a
   usable executable path.

All command variants go through the existing bounded binary process collector,
so the module fallback does not change the 8 MiB per-stream output boundary,
timeouts, exit codes, or report schema.

## Verification

The regression simulates an absent PATH executable and asserts the current
Python module command and version output. The real CLI is exercised with the
repository venv without modifying `PATH`.
