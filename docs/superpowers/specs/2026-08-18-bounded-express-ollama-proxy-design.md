# Bounded Express Ollama Proxy Design

## Problem

The Express Ollama proxy accumulates upstream model, chat, status, and stream
responses without a byte budget. Python Ollama paths are bounded, but callers
using the Express service can still make Node retain arbitrarily large response
strings before JSON or NDJSON parsing.

## Decision

- Define an 8 MiB Express Ollama upstream response budget.
- Add a shared non-stream response collector that counts raw Buffer bytes,
  stops at the first byte beyond the budget, destroys the upstream response,
  and invokes a caller-specific existing error path.
- Apply the collector to `/api/ollama/models`, `/api/ollama/chat`, and
  `/api/ollama/status`, preserving their current 502 error codes and messages.
- Apply the same cumulative byte counter to streaming chat, destroy the
  upstream response on overflow, and emit one existing-format
  `OLLAMA_STREAM_ERROR` SSE frame before ending the client response.
- Keep the 32 KiB request parser limit, valid response shapes, token accounting,
  and normal SSE framing unchanged.

## Alternatives

1. Bound only JSON parsing after accumulation. This still retains the complete
   malicious body and does not solve the resource issue.
2. Use a fixed upstream `Content-Length` check only. Chunked responses can
   omit or falsify that header, so a cumulative byte counter is required.

## Compatibility

Valid responses at or below 8 MiB retain existing JSON and SSE behavior.
Oversized responses use the existing upstream/invalid-response envelopes or
stream error frame; no new public API is introduced.

## Verification Contract

Node integration tests make the fixture stream more than 8 MiB and assert the
proxy closes before the fixture finishes sending. They cover non-stream models,
chat/status overflow, and streaming overflow while preserving current success
and upstream-error tests. Vitest, typecheck, build, E2E, and Python aggregate
tests must pass.
