# Bounded API Query Inputs Design

## Goal

Keep every first-party `/api/` adapter from materializing an unbounded raw query
string. Requests whose raw UTF-8 query portion is larger than 32 KiB return the
existing `REQUEST_QUERY_TOO_LARGE` `ErrorResponse` with status 413 before route
handlers, framework query parsing, or Core API proxying run.

## Context and options

The previous iteration protected only the Python Ollama stream handler. The
same stream route is also served by Express, while several other routes parse
query values before validation. Three approaches were considered:

1. Add a separate check to every route. This keeps changes local but repeats
   byte accounting and leaves future routes easy to miss.
2. Add one adapter ingress middleware for `/api/` requests, with existing
   route-specific validation retained. This gives a uniform early boundary and
   keeps semantic validation where it belongs. This is the selected approach.
3. Rely on server parser defaults. This is not sufficient because limits differ
   between adapters and do not produce the stable API error envelope.

## Architecture and data flow

- `src/main.py` checks the raw query in each API request routing entry before
  dispatching the route. The existing stream value checks remain defense in
  depth for decoded values and JSON parsing.
- `src/main_fastapi.py` adds an ASGI middleware that reads only
  `scope["query_string"]`, rejects over-budget `/api/` requests, and otherwise
  delegates unchanged. The body middleware and FastAPI parameter validation
  continue to handle their existing responsibilities.
- `frontend/server.js` adds an Express middleware that measures the raw query
  from `req.originalUrl` before any proxy or `req.query` consumer. Its HTTP
  server uses a bounded 64 KiB header envelope so a valid 32 KiB API query can
  reach the middleware; the application-level query budget remains 32 KiB.

The limit counts bytes after `?` exactly as received on the wire. It is not a
decoded character count and it does not alter valid query values. The response
body is `{ "error": { "code": "REQUEST_QUERY_TOO_LARGE", "message":
"Request query exceeds the 32 KiB limit" } }`.

## Contract and testing

The shared OpenAPI document declares the 413 response for every documented
operation with query parameters. Regression tests cover exact-limit acceptance,
one-byte overflow, route short-circuiting in the Python and FastAPI adapters,
Express API responses, and the OpenAPI response shape. Existing stream-level
decoded-value checks and all prior response behavior remain unchanged.

## Scope and risks

Only `/api/` requests are subject to this application boundary; static frontend
assets and unrelated paths keep their existing behavior. Raising the Node
header parser ceiling is paired with the smaller application query budget and
does not remove a finite transport limit. No new dependency or public write
operation is introduced.
