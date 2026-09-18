# Memory Endpoint Test State Isolation Design

## Problem

Several HTTP and FastAPI endpoint tests exercise successful memory writes through
the process-global application state. Running the repository test suites therefore
creates deterministic fixture entries in the real `.auto-memory` directory. The
current workspace contains the six corresponding fixture records, including an
empty-title record, so this is an observed resource-ownership defect rather than a
hypothetical risk.

The test suite must never write user memory. Existing user data must not be deleted,
rewritten, or used as a test oracle.

## Approaches Considered

1. Inject an isolated memory-owning state into each mutating endpoint test. This is
   the selected approach because both service adapters already expose the required
   seams: stdlib handlers accept `app_state`, and FastAPI exposes
   `AppState(memory_dir=...)` plus `create_app(state)`.
2. Change the working directory or `JARVIS_MEMORY_DIR` for the whole test process.
   This has a wider blast radius because repository, Plugin, Git, and path-boundary
   tests intentionally depend on the project working directory.
3. Add production-only test-mode detection. This would couple runtime behavior to
   the test harness and is unnecessary while explicit dependency injection exists.

## Design

Each of the six known write tests owns a `TemporaryDirectory` for the duration of
the request. The stdlib tests construct a `MemoryStore` rooted there and pass it in
the handler's `app_state`. The FastAPI tests construct an isolated `AppState`, bind
it through `create_app`, and use `TestClient` as a context manager so lifespan
shutdown completes before the directory is removed.

A discovery-only regression runs the six write tests while replacing every process-
global memory store's `store()` method with a failure sentinel. The nested tests may
write only through their isolated stores. This checks behavior instead of relying on
source-text conventions and catches future regressions that accidentally return to
the default state.

## Error Handling and Cleanup

Temporary application states are shut down by the FastAPI lifespan before their
directories are removed. Stdlib tests create only an isolated `MemoryStore`, so no
additional process resources are introduced. The guard reports the nested unittest
errors and failures if any default store is reached.

No cleanup is performed against the existing `.auto-memory` directory; its contents
may be user data and remain outside this change's authority.

## Acceptance Criteria

- The isolation guard fails against the pre-change tests for the expected default-
  store access.
- All six endpoint write tests pass while every global memory store rejects writes.
- The four affected test modules and the isolation guard pass normally.
- Relevant aggregate/discovery, Ruff, compile, frontend, and diff checks pass.
- Public Memory API behavior and production storage paths remain unchanged.

