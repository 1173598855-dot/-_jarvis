# Production Role Execution Design

**Iteration:** 126
**Date:** 2026-07-15
**Status:** Approved by autonomous continuation directive

## Goal

Replace the deterministic role response used by the two Python service adapters
with real Ollama-backed execution while preserving the existing role registry,
orchestrator, public API contract, and standalone `AgentFactory` compatibility.

## Context

Iteration 125 aligned role routes across Python HTTPServer, FastAPI, and Express,
but `AgentFactory._default_handler()` still returns a truncated "Task received"
string. The factory already accepts an `ollama_manager`, yet neither application
state injects its manager. The unused `dispatch_llm()` path also calls
`OllamaManager.chat()` with an incompatible signature.

The repository already owns the required runtime, deterministic Ollama fixture,
and three-adapter contract harness. Adding another agent framework would duplicate
those capabilities and add an unnecessary dependency.

## Chosen Approach

Extend the existing `AgentFactory` integration point instead of introducing a
new policy hierarchy:

1. Both Python `AppState` implementations pass their existing `OllamaManager` to
   `AgentFactory`.
2. A factory with an injected manager registers role handlers that call
   `OllamaManager.chat(model, messages, stream=False)`.
3. A factory without a manager retains the deterministic handler for standalone
   library tests and the legacy CLI. Production service states never use this
   compatibility path.
4. The role model defaults to `llama3.2` and can be set through the trusted
   process environment variable `JARVIS_ROLE_MODEL`.
5. `dispatch_llm()` uses the same valid Ollama chat signature when asking the
   model to select a role.

This is the smallest change that closes the production behavior gap while
keeping model access and token accounting centralized in `OllamaManager`.

## Components

### AgentFactory

`AgentFactory` owns role-to-task translation. It will:

- build a system message from the resolved role identity, description,
  constraints, and declared tools;
- send the original user task as a separate user message;
- keep the full resolved prompt in `AgentTask.prompt` for orchestrator history;
- validate that the manager response contains a non-empty assistant content
  string;
- raise a stable execution error when Ollama returns an error or an invalid
  response, allowing `Orchestrator` to record an `error` result;
- return the assistant content through the existing `DispatchResult.message`.

Role `tools` remain prompt metadata only. This iteration does not grant tool
execution or change any terminal/plugin permission boundary.

### Application State

Python HTTPServer and FastAPI each create one `OllamaManager`. That same instance
is injected into their `AgentFactory`, so role calls use the configured base URL
and contribute to the existing token-usage snapshot. No second HTTP session or
model client is created.

### Public API

Route names, request bodies, HTTP status codes, and `DispatchResult` fields stay
unchanged. A reachable fixture/model returns `status: "success"` with actual
assistant content. An upstream failure remains a completed dispatch response with
`status: "error"` and an explicit, sanitized message; the orchestrator history
records the same failure. Batch dispatch continues to report failures per item.

## Data Flow

1. A role route validates `role_name` or `capability`, `prompt`, and `timeout`.
2. `AgentFactory` selects and resolves an `AgentProfile`.
3. The factory registers an Ollama-backed handler with `Orchestrator` on first use.
4. `Orchestrator` executes the handler with the existing timeout and history
   semantics.
5. The handler calls the shared `OllamaManager` with system and user messages.
6. The factory maps the resulting `AgentResult` to the existing
   `DispatchResult`; Express transparently proxies the Core response.

## Error Handling

- Manager response containing `error`: dispatch status is `error` and the public
  message states that Ollama role execution failed without exposing exception
  representations or transport internals.
- Missing or blank assistant content: treated as an invalid upstream response and
  recorded as an error.
- Timeout: existing orchestrator timeout behavior remains authoritative.
- Missing role/capability and invalid request: existing 400/404 envelopes remain
  unchanged.
- No manager in a directly constructed factory: deterministic compatibility
  handler remains available, but this path is not used by either HTTP service.

## Testing

The implementation will follow a red-green sequence:

1. Agent factory tests prove the injected manager receives the configured model,
   system/user messages, and `stream=False`, and that valid/error/invalid manager
   responses map correctly.
2. App-state tests prove both service adapters inject exactly their own manager.
3. The local Ollama fixture and live three-adapter contract test prove role
   dispatch returns fixture-generated content rather than the compatibility
   "Task received" response.
4. Focused Python and frontend proxy tests run before the aggregate Python suite,
   complete discovery, compile checks, Vitest, Playwright, typecheck, and build.

## Documentation And Delivery

- Record the Phase 3 search and no-dependency decision in
  `docs/reports/GITHUB_LEARNING_REPORT.md`.
- Update configuration documentation for `JARVIS_ROLE_MODEL`.
- Add Iteration 126 to `CHANGELOG.md`, roll audit reports to retain the latest ten,
  update project analysis, and create `AUDIT_REPORT_126.md` with current evidence.

## Non-Goals

- Tool calling or arbitrary command execution by roles.
- Streaming role responses.
- A new provider abstraction or external agent framework.
- Changes to role selection priority, public route shapes, or Express proxy logic.
