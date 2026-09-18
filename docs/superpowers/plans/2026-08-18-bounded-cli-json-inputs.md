# Bounded CLI JSON Inputs Implementation Plan

**Goal:** Bound every remaining local CLI JSON file read without changing
in-limit command behavior.

## Tasks

- [x] Add RED tests for exact-limit, growth, UTF-8, valid batch, and oversized
  input behavior.
- [x] Implement and reuse the shared bounded JSON reader.
- [x] Restore AgentFactory CLI success exits while preserving error exits.
- [x] Make all three documented CLI scripts runnable without `PYTHONPATH`.
- [x] Register the tests in the aggregate suite.
- [x] Run self-review, aggregate/discovery tests, compileall, Ruff, and diff
  checks.
