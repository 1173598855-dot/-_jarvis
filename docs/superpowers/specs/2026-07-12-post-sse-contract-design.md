# POST SSE Contract Design

## Context and decision

The browser chat client already uses `POST /api/ollama/chat/stream`, but the shared OpenAPI document and both Python service implementations only expose the GET form. This makes the documented, user-facing streaming route fail when a Python service is used directly.

Three options were considered:

1. Convert the browser client to GET and encode messages in the URL. This preserves the existing Python routes but imposes URL-size and encoding limits.
2. Keep POST only in Express. This leaves the shared contract and replacement service boundary broken.
3. Add a POST alias to all three implementations while retaining GET for EventSource compatibility. This is the selected option because it preserves both client modes and gives all services one canonical wire contract.

The active continuous-iteration instruction authorizes this focused design without an additional approval pause.

## Contract

`POST /api/ollama/chat/stream` accepts a JSON object with optional `model` (non-empty string) and `messages` (array). A valid request returns `200 text/event-stream`. Its content frames use `SseContentFrame`; an upstream failure uses `SseErrorFrame` and does not emit `[DONE]`.

Malformed JSON must return `400 INVALID_JSON`; a non-object JSON body must return `400 INVALID_REQUEST`. The existing GET endpoint remains unchanged for URL-driven EventSource clients.

## Implementation boundaries

- `contracts/core-api.openapi.json` is the single declaration for both GET and POST.
- `src/main.py` parses POST bodies through its existing JSON validator, then reuses one SSE writer.
- `src/main_fastapi.py` reuses one streaming-response constructor for GET and POST.
- `frontend/server.js` retains its existing POST adapter and adds input-object validation so all implementations reject the same malformed shape.
- Loopback integration tests prove all three public services accept the same POST request and produce the canonical stream.

## Verification

Tests first assert the missing POST operation, then verify it becomes declared. A second test sends the same request to Python HTTPServer, FastAPI, and Express and validates frame shape, one `done: true` content frame, and exactly one `[DONE]` terminator. Focused unit tests cover Python route selection and malformed requests before the full delivery gate.
