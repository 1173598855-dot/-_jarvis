# MemoryStore Entry Target Boundary Implementation Plan

**Goal:** Prevent `MemoryStore.store()` from following a pre-existing redirect
or non-regular entry target.

- [x] Add a RED symlink regression proving the old write followed an external
  target.
- [x] Add an `lstat()` regular/non-reparse preflight before body construction.
- [ ] Run MemoryStore, aggregate/discovery, compile, lint, integration, and
  repository consistency gates; update Iteration 193 ledgers.
