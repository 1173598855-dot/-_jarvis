# Ruff Helper Module Fallback Implementation Plan

**Goal:** Make the documented local Ruff helper work when Ruff is installed in
the active Python environment but its executable directory is not in `PATH`.

- [x] Add a failing regression for the missing-PATH/module-present case.
- [x] Resolve Ruff through PATH first and current Python `-m ruff` second.
- [x] Preserve the existing bounded process collector and command contracts.
- [x] Update iteration evidence and test counts.
- [x] Run the final full verification and self-review after documentation sync.
