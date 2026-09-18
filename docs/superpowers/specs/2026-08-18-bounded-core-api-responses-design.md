# Bounded Core API Response Design

## Problem

The Express Core API client clears its timeout as soon as `fetch()` returns
headers, then calls `Response.json()`. A Core service can therefore make the
BFF retain an arbitrarily large body or wait forever while the body is still
streaming.

## Decision

- Keep the existing Fetch-based client and its public `{ status, body }`
  result.
- Apply a fixed 8 MiB raw-byte response budget before UTF-8 decoding and JSON
  parsing.
- Reject a numeric `Content-Length` above the budget immediately, but always
  enforce the cumulative stream count because the header can be absent or
  inaccurate.
- Read `response.body` through its reader, cancel it on the first byte beyond
  the budget without waiting for untrusted cancellation cleanup, and never
  call `response.json()` or `response.arrayBuffer()`.
- Keep the request timeout active until the complete body has been parsed.
  Abort and cancel the body reader when the deadline expires.
- Preserve error categories: connection failures and deadline expiry remain
  `CORE_API_UNAVAILABLE`; oversized, unreadable, empty, or malformed JSON
  remains `CORE_API_INVALID_RESPONSE`.

## Alternatives

1. `response.arrayBuffer()` followed by a length check was rejected because it
   materializes the entire untrusted response before enforcing the limit.
2. Replacing Fetch with `http.request()` was rejected because it would
   duplicate transport behavior already owned by Fetch and expand the change
   beyond the response boundary.

## Compatibility

Valid JSON responses at or below 8 MiB keep the same status and parsed body.
Existing base-URL normalization, request initialization, per-request timeout
overrides, capability probing, and Express error envelopes remain unchanged.
No environment variable or public API field is added.

## Verification Contract

- A chunked response without `Content-Length` is cancelled exactly when its
  cumulative bytes exceed 8 MiB and returns `CORE_API_INVALID_RESPONSE`.
- An oversized declared `Content-Length` is cancelled before its body is read.
- A cancellation promise that never settles cannot delay the bounded error.
- A body that stalls after headers is aborted at the effective request timeout
  and returns `CORE_API_UNAVAILABLE`.
- Existing JSON forwarding, invalid JSON, unavailable-service, timeout
  override, server bridge, frontend, E2E, Python, lint, build, and integration
  gates continue to pass.
