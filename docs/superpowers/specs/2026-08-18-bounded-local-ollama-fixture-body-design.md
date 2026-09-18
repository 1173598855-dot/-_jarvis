# Bounded Local Ollama Fixture Request Body Design

## Context

The local Ollama fixture used by required-services integration read the entire
declared `Content-Length` from `rfile` before JSON parsing. A malformed local
client could therefore make the test service retain an arbitrary request body.

## Decision

Add `MAX_FIXTURE_REQUEST_BYTES = 32 * 1024` and a small request-body helper.
Validate a plain non-negative integer `Content-Length` before reading, read only
that declared bounded amount, require a byte body and a JSON object, and map
known failures to the existing 400 `invalid request` fixture response.

## Compatibility

Valid deterministic `/api/chat` tool-call and non-stream responses are unchanged.
Missing `Content-Length` continues to produce an empty object request. This is a
test fixture boundary and does not alter the public Python/FastAPI body guards.

## Testing

Regression coverage proves an oversized declaration is rejected before the
stream is read and keeps the existing two-step tool round trip green.
