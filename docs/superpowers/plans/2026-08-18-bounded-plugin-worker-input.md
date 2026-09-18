# Bounded Plugin Worker Input Implementation Plan

**Goal:** Prevent the child Plugin Worker from reading an unbounded protocol
line before its existing decoder applies the 64 KiB wire limit.

## Tasks

- [x] Add a RED regression that records the child `readline` size.
- [x] Bound lifecycle and Broker-response reads with one sentinel byte.
- [x] Include the entrypoint suite in the canonical aggregate runner.
- [x] Update the iteration ledger and report navigation.
- [x] Run targeted, aggregate, discovery, compileall, Ruff, integration, and
  diff checks.
