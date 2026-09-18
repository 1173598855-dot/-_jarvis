# Bounded Orchestrator History Design

## Context

`Orchestrator` is owned for the lifetime of each Python service. Its task
history is currently an unbounded list, `collect(limit=0)` returns every
record because `-0` is zero, and filtering happens after the recent window is
selected. Stored `AgentResult` objects are also shared with dispatch callers
and later `collect()` callers, so either side can rewrite retained evidence.

## Decision

- Retain the newest 1000 results in a `deque`.
- Deep-copy a result when recording it and deep-copy selected results when
  returning them.
- Accept only exact non-negative integer query limits; zero returns an empty
  result without special slicing behavior.
- Apply all optional filters to newest-first retained history before applying
  the result limit.
- Keep dispatch return values, stats, retry behavior, and API response shapes
  unchanged.

## Verification

Regression coverage proves capacity and order, query-limit validation,
filter-before-limit behavior, and nested result ownership at both the record
and read boundaries. The class is then registered exactly once in the
canonical aggregate suite before focused and full project gates run.
