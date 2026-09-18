# Chunked Request-Body Limit Design

## Context and decision

Iteration 115 rejects bodies above 32 KiB when `Content-Length` declares their size. ASGI clients may instead stream a body in multiple `http.request` messages without that header, so FastAPI needs a receive-layer counter to preserve the same boundary.

Options considered:

1. Reject every request without `Content-Length`. This is simple but needlessly breaks valid chunked JSON clients.
2. Rely on Uvicorn/proxy configuration. This leaves the in-process contract unverified and environment-dependent.
3. Wrap ASGI `receive`, count chunks, and issue the same 413 before forwarding an over-limit sequence to the downstream app. This is selected because it permits valid chunked requests up to the limit and gives a deterministic in-process boundary.

The continuous-iteration instruction authorizes this focused design without an approval pause.

## Behavior

The FastAPI middleware keeps its preflight `Content-Length` check. When the header is absent, it counts `http.request.body` bytes. It rejects once the accumulated size exceeds 32 KiB, or when exactly 32 KiB has arrived with `more_body: true`, because the final total must then exceed the limit.

The middleware sends the existing `413 REQUEST_BODY_TOO_LARGE` JSON envelope, returns `http.disconnect` to downstream code, and suppresses any downstream response after that terminal error. A chunked body ending exactly at 32 KiB remains valid.

## Verification

An ASGI unit test feeds a headerless two-chunk sequence whose first chunk is exactly 32 KiB and still has `more_body: true`. Before implementation, downstream receives the first chunk. After implementation, it receives only `http.disconnect` and the captured response is a 413 ErrorResponse.
