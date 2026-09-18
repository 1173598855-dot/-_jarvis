# Bounded Stream Query Inputs Design

## Problem

The GET `/api/ollama/chat/stream` routes in the standard-library HTTP service
and FastAPI accept arbitrary `model` and JSON-encoded `messages` query values.
POST requests already have a 32 KiB body boundary, but GET values can be
materialized and parsed without the same limit before reaching Ollama.

## Decision

- Reuse the exact 32 KiB UTF-8 budget used for request bodies.
- In `src/main.py`, reject the raw query string before `parse_qs`, then check
  decoded model/messages values before `json.loads` or upstream dispatch.
- In `src/main_fastapi.py`, declare the same character ceiling through FastAPI
  `Query`, map query length validation to a 413 `REQUEST_QUERY_TOO_LARGE`
  envelope, and perform an explicit UTF-8 byte check for multibyte values.
- Add `maxLength: 32768` to the OpenAPI GET query schemas and declare the 413
  error response. Existing valid fallback parsing and SSE framing remain.

## Alternatives

1. Truncating oversized messages was rejected because it silently changes a
   user's prompt and can produce invalid JSON.
2. Capping only decoded `messages` was rejected because `parse_qs` would first
   materialize an oversized raw query and percent-decoding can expand bytes.
3. Increasing the global body limit was rejected because it weakens existing
   POST protection and does not bound GET query allocation.

## Verification Contract

- A raw query over 32 KiB is rejected before `parse_qs` in the standard server.
- A percent-decoded or multibyte value over 32 KiB is rejected before JSON
  parsing/upstream dispatch in both services.
- Exact-limit valid query requests preserve existing stream behavior.
- The public error is HTTP 413 with `REQUEST_QUERY_TOO_LARGE` and the stable
  message `Request query exceeds the 32 KiB limit`.
