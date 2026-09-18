# Non-Streaming Ollama Error Contract Design

## Context and decision

The three `/api/ollama/chat` implementations currently expose upstream failure differently: Python HTTPServer returns `200` with a string error, FastAPI returns a generic `500 HTTP_500`, and Express forwards the upstream status/body unchanged. The endpoint is also absent from the shared OpenAPI contract.

Options considered:

1. Preserve raw upstream status/message for diagnosability. This keeps implementation details and response shapes unstable.
2. Add detailed manager error subclasses in this iteration. This would improve categories but expands the internal API and requires error-source migration.
3. Normalize every non-streaming upstream failure at the public boundary to one `502 OLLAMA_UPSTREAM_ERROR` envelope with a generic message. This is selected because it removes drift immediately without parsing unstable localized exception strings.

The continuous-iteration request authorizes this focused design without an additional approval pause.

## Contract

`POST /api/ollama/chat` accepts a JSON object containing optional `model`, `messages`, and `stream`. `stream` is fixed to `false`; callers use `/api/ollama/chat/stream` for SSE. Successful responses expose model, assistant message, completion state, and optional token counters.

Malformed/invalid bodies and `stream: true` return `400 INVALID_REQUEST`. Any upstream HTTP, connection, timeout, or invalid non-stream JSON result returns:

```json
{
  "error": {
    "code": "OLLAMA_UPSTREAM_ERROR",
    "message": "Ollama chat request failed"
  }
}
```

with HTTP 502. Oversized bodies retain the shared 413 response.

## Implementation boundaries

- `contracts/core-api.openapi.json` declares `OllamaChatRequest`, `OllamaChatResponse`, and post responses 200/400/413/502.
- `src/main.py` and `src/main_fastapi.py` force the manager call to non-streaming and map its internal `error` key at the HTTP boundary.
- `frontend/server.js` gets a dedicated non-stream proxy which buffers a successful JSON result, records tokens only on success, and never forwards raw upstream errors or invalid JSON.
- The existing loopback Ollama fixture gains a deterministic 500 mode; one cross-service test validates both success shape and the shared error result.

## Security properties

The public 502 does not echo upstream body text, Node transport errors, or manager exception strings. Rejected `stream: true` requests do not start an upstream request.
