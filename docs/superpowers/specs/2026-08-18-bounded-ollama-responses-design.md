# Bounded Ollama Response Design

## Problem

`OllamaManager` decoded non-streaming responses with `Response.json()` and
consumed streaming responses through `iter_lines()`. Both paths could
materialize an unbounded upstream body before the service validated it. The
optional local integration profile had the same issue through `json.load()` and
`response.read()`.

## Decision

- `OllamaManager` reads non-streaming responses through bounded
  `iter_content()` chunks with an 8 MiB total body limit.
- NDJSON pull/chat streams use the same 8 MiB total limit, a 64 KiB line limit,
  and a fixed 8 KiB transport chunk size. Lines may span chunks and an exact
  limit remains valid; the first byte beyond a limit fails closed.
- The local integration profile uses a shared 8 MiB bounded `read(limit + 1)`
  helper for JSON, HTTP error bodies, and SSE payloads. The SSE parser also
  rejects an already-materialized string over that budget.
- Existing public result shapes and service-level error handling remain
  unchanged; oversized responses become the existing error/failure paths.

## Non-Goals

This does not truncate valid model output, change Ollama request payloads, or
introduce an OS-level network sandbox. It only rejects upstream responses that
exceed the explicit safety budgets.

## Verification Contract

Regression tests cover oversized body, string `Content-Length`, oversized line,
and cumulative stream input. The local integration runner must pass against the
repository-owned Ollama fixture.
