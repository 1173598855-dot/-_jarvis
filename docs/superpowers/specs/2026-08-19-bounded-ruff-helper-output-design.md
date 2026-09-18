# Bounded Ruff Helper Output Design

## Context

`scripts/ruff_check.py` invokes Ruff with `subprocess.run(...,
capture_output=True)`. A malformed or unexpectedly noisy local Ruff process can
therefore grow stdout and stderr without a byte boundary before JSON or diff
parsing.

## Decision

Run Ruff through `subprocess.Popen` with binary pipes and drain stdout and
stderr concurrently. Retain at most 8 MiB of raw bytes per stream, stop at the
first byte beyond either limit, kill the child, and return the existing `-1`
execution-failure shape with a stable bounded-output diagnostic. Keep the
existing 10-second version probe, 120-second lint/format deadline, exit codes,
UTF-8 replacement decoding, and parsing behavior for valid output.

## Safety Invariants

- Never retain or decode more than 8 MiB per child stream.
- Never parse partial lint JSON or format diff after an overflow.
- Drain stdout and stderr concurrently so a noisy child cannot deadlock on the
  other pipe.
- Kill at most once on overflow or timeout and close both streams after the
  child is reaped.
- Do not change Ruff arguments, working-directory handling, or report schema.

## Verification

Unit tests cover bounded successful output, independent stdout and stderr
overflow, child termination, and an oversized `ruff --version` response.
Compileall, Ruff, aggregate/discovery tests, and the existing frontend and
integration checks provide the delivery evidence.
