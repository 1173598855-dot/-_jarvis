# Shared Request-Body Limit Design

## Context and decision

Express already limits JSON requests to 32 KiB, while Python HTTPServer reads the declared body length without a ceiling and FastAPI relies on its hosting boundary. The newly supported POST SSE path makes that drift a concrete, cross-service API concern.

Options considered:

1. Document a deployment-proxy limit only. This leaves direct local services unprotected and untestable.
2. Apply independent limits only to the chat stream endpoint. This avoids the immediate route risk but gives callers inconsistent server behavior.
3. Establish one 32 KiB JSON request boundary in each service and expose a stable `413 REQUEST_BODY_TOO_LARGE` envelope. This is selected because it matches the existing Express limit and protects all body-reading routes without adding a dependency.

The continuous-iteration request authorizes this focused design without a separate approval pause.

## Contract

All three services reject a JSON request body whose declared `Content-Length` exceeds 32 KiB with:

```json
{
  "error": {
    "code": "REQUEST_BODY_TOO_LARGE",
    "message": "Request body exceeds the 32 KiB limit"
  }
}
```

The public `POST /api/ollama/chat/stream` OpenAPI operation declares the 413 `ErrorResponse`. Existing malformed-body behavior remains `400 INVALID_JSON` or `400 INVALID_REQUEST`.

## Implementation boundaries

- `src/main.py` centralizes the limit immediately after parsing `Content-Length`; its existing typed request error flow maps the failure to 413.
- `src/main_fastapi.py` adds a small outer ASGI middleware that rejects an oversized declared body before Pydantic reads it.
- `frontend/server.js` maps Express body-parser's `entity.too.large` error to the same nested error envelope.
- Tests submit one 32 KiB-plus JSON payload to the same POST stream endpoint on all three services.

## Security properties

The limit is independent of model, message content, and upstream availability; rejected payloads never reach Ollama or a stream generator. The check uses byte length rather than character count and returns no request content in the error response.
