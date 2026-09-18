# Bounded LLM Compression History Design

## Context

`LLMCompressor` records one dictionary for every pruned, summarized, or
fallback memory entry. The list grows for the lifetime of the compressor and
the public property copies only the list container, leaving stored dictionaries
owned by callers after a read.

## Decision

- Retain the newest 1000 compression records in a fixed-capacity deque.
- Protect append, snapshot, and clear operations with one instance lock.
- Return separate scalar dictionaries from `compression_history`.
- Keep record fields, oldest-to-newest order, compression behavior, and clear
  semantics unchanged.
- Register the focused history test class exactly once in the canonical
  aggregate suite.

## Verification

A 1005-record regression proves deterministic oldest-entry eviction. A nested
mutation regression proves returned dictionaries cannot rewrite retained
evidence. Existing LLM and adaptive compression tests protect behavior outside
the history boundary.
