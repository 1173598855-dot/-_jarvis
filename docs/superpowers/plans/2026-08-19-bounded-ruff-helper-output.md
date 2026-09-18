# Bounded Ruff Helper Output Implementation Plan

**Goal:** Bound local Ruff quality-helper subprocess output before any parsing.

**Architecture:** Replace `subprocess.run(capture_output=True)` with a small
binary `Popen` collector that drains both pipes concurrently, enforces an 8 MiB
per-stream budget, and preserves the helper's current result tuple and error
contracts.

## Tasks

- [x] Add RED tests for normal output, stdout overflow, stderr overflow, and
  oversized version output.
- [x] Implement the bounded collector and route version, lint, and format
  invocations through it.
- [x] Run focused tests, compileall, and Ruff.
- [x] Update the iteration ledger and current-state documentation with fresh
  counts.
- [x] Run the full Python and frontend verification gates and perform the final
  diff/self-review.
