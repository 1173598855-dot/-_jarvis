# Token Usage State Ownership Design

## Context

Each Python service shares one `OllamaManager` across HTTP chat, synchronous
role dispatch, asynchronous role Workers, and telemetry reads. Token totals,
latest usage, and the 60-sample series are currently updated without a common
lock. `get_token_usage()` also returns the internal mutable dataclass, allowing
an internal consumer to rewrite session totals.

## Decision

- Protect totals, latest usage, samples, and their snapshots with one lock.
- Store the newest 60 samples in a fixed-capacity deque.
- Return a new `TokenUsage` value from `get_token_usage()`.
- Continue returning independent scalar dictionaries from the HTTP snapshot.
- Preserve negative-value clamping, compatible response parsing, sample
  schema, and session start semantics.

## Verification

Deterministic concurrent recording uses a yielding `TokenUsage` test value to
prove that unprotected read-modify-write loses updates. Separate regressions
prove getter ownership and 60-entry FIFO retention. The full `TestTokenUsage`
class is then registered exactly once in the canonical aggregate suite.
