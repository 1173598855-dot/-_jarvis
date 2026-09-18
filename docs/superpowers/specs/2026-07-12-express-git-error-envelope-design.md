# Express Git Error Envelope Design

**Date:** 2026-07-12
**Iteration:** 113
**Status:** Approved by the project’s automatic continuous-iteration protocol

## Objective

Remove the remaining string-shaped error responses from Express Git metadata endpoints without adding a dependency or changing successful response payloads.

## Context

GET /api/git/status, GET /api/git/log, and GET /api/git/branches currently catch a Git execution failure and return { error: err.message }. This violates the established public shape { error: { code, message } } and can expose environment-specific executable errors.

## Options Considered

1. **Use the existing sendApiError helper — selected.** Return 500 GIT_COMMAND_FAILED with a stable generic message. Add an error listener to the child process and an environment-only Git executable override for deterministic integration tests.
2. **Add http-errors or zalando/problem.** These maintained MIT candidates offer helpers and RFC-style semantics, but add a dependency and would still require a migration of the project’s established response shape.
3. **Migrate every Express error path to RFC 9457 now.** This would be broader than the P1 Git scope and risks a client-wide breaking change.

## Design

- server.js defines GIT_COMMAND from JARVIS_GIT_COMMAND or the trusted default git.
- runGitCommand listens for the child-process error event and rejects once; normal close handling remains unchanged.
- Every Git route catch uses sendApiError(res, 500, 'GIT_COMMAND_FAILED', 'Git repository metadata is unavailable').
- The override is process configuration only, never request input, and exists to make the unavailable-executable path testable.
- frontend/server.test.js launches its existing Express fixture with a non-existent JARVIS_GIT_COMMAND and asserts the status endpoint returns ErrorResponse. Successful Git endpoint behavior is not changed.
- docs/SETUP.md documents the variable as a test and deployment diagnostic override, not a browser-facing capability.

## Acceptance Criteria

- A missing Git executable returns HTTP 500 with error.code GIT_COMMAND_FAILED and a non-empty stable message.
- The Node process remains alive after spawn emits an error.
- Normal server tests, browser E2E, typecheck, build, and Python verification remain green.
- No new runtime or development dependency is added.
