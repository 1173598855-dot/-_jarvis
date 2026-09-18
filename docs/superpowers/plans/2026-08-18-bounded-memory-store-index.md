# Bounded MemoryStore Index Reads Implementation Plan

**Goal:** Prevent writable MemoryStore index mutations from allocating an
unbounded `MEMORY.md` snapshot or deleting a probe before index validation.

- [x] Add RED regressions for oversized index rejection, exact-limit reads,
  stat-underreported growth, and probe preservation.
- [x] Reuse the regular-file descriptor reader for an 8 MiB index budget and
  reject redirecting/dangling index links during initialization.
- [x] Validate the index before entry publication and probe deletion.
- [x] Move concurrency test hooks from `Path.read_text()` to the bounded helper.
- [x] Run MemoryStore, aggregate/discovery, compile, lint, integration, and
  frontend gates; update the rolling report and project ledgers.
