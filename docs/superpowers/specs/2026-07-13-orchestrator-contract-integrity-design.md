# Orchestrator Contract Integrity Design

**Date:** 2026-07-13
**Iteration:** 124
**Status:** Approved for implementation

## Goal

Restore evidence-backed parity for the shared orchestrator contract across the
Python HTTPServer, FastAPI, and Express adapters. The public behavior must
match the existing OpenAPI contract and the actual runtime behavior, including
history limits, dispatch parameters, success payloads, and error envelopes.

## Scope

This iteration is deliberately limited to the shared orchestrator subset:

- `GET /api/orchestrator/agents`
- `GET /api/orchestrator/history`
- `POST /api/orchestrator/dispatch`

The work will:

1. Enforce `history.limit` in the inclusive range `1..100` in FastAPI and
   document the same maximum in OpenAPI.
2. Make Python HTTPServer dispatch honor the same `timeout` and `priority`
   request semantics as FastAPI. The public defaults are `timeout=300` and
   `priority=1`; `priority` remains bounded to `0..3`.
3. Extend the real three-adapter contract harness so it invokes the dispatch
   success path and validates the declared `AgentResult` shape.
4. Correct Express test fixtures so successful dispatch responses contain all
   fields required by `AgentResult`.
5. Extend the local schema validator to enforce `maximum`, because the shared
   OpenAPI already uses it for dispatch priority.

Role-specific endpoints remain out of scope. They will be designed separately
after their status and payload semantics are unified across adapters.

## Architecture and Data Flow

The shared OpenAPI file remains the single machine-readable contract. Requests
enter one of three adapters:

```text
client
  -> Python HTTPServer / FastAPI / Express
  -> Orchestrator dispatch adapter
  -> core.brain.orchestrator.Orchestrator
  -> AgentResult
  -> adapter JSON response
```

The adapters may retain framework-specific parsing, but they must expose the
same observable values:

- missing `agent_name` or `prompt`: `400 ErrorResponse`;
- `timeout`: integer with default `300`, minimum `1`, and maximum `300`;
- `priority`: integer with default `1`, minimum `0`, maximum `3`;
- history `limit`: integer with default `10`, minimum `1`, maximum `100`;
- dispatch success: the existing `AgentResult` schema, including nullable
  result/error values as emitted by the core implementation.

No adapter will call an external model for this iteration. Existing local
orchestrator handlers and deterministic fixtures remain the source of test
success responses.

## Error Handling

All JSON errors use the existing nested envelope:

```json
{"error":{"code":"...","message":"..."}}
```

Malformed JSON uses `INVALID_JSON`/`400`; non-object bodies, invalid fields,
whitespace-only text, and unpaired Unicode surrogates use
`INVALID_REQUEST`/`400`. Express Core proxy failures
continue to map to `CORE_API_NOT_CONFIGURED`/`503` and
`CORE_API_UNAVAILABLE` or `CORE_API_INVALID_RESPONSE`/`502`.

## Testing Strategy

- Add a failing FastAPI regression for history limits above `100`.
- Add a failing HTTPServer regression proving dispatch forwards `timeout` and
  `priority`.
- Add a failing schema-validator regression for `maximum`.
- Extend the real loopback harness to dispatch through Python HTTPServer,
  FastAPI, and Express and validate `AgentResult`.
- Correct and assert the Express Core fixture's complete dispatch response.
- Run targeted Python tests, aggregate and full discovery suites, frontend
  Vitest, TypeScript typecheck, build, E2E, compileall, and `git diff --check`.

## Out of Scope

- `/api/roles*` parity or role-specific OpenAPI schemas.
- New runtime dependencies.
- Frontend role UI.
- Changes to terminal allowlists, capability tokens, or OS-level sandboxing.
- Rewriting the core Orchestrator or changing its internal result model.
