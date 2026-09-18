# EventBus State Boundaries Design

## Context

Each Python service shares an `EventBus` across plugin lifecycle publication,
subscribers, and HTTP history reads. Subscriber IDs are read and incremented
before acquiring the bus lock, so concurrent subscriptions can reserve the
same ID. History slicing also treats zero as the complete history and accepts
negative or boolean limits.

## Decision

- Reserve each subscription ID and append its subscriber record in one lock
  acquisition.
- Require history limits to be exact non-negative integers.
- Return an empty history for a zero limit and keep filter-before-limit order.
- Preserve chronological reads, the fixed history deque, callback execution
  outside the lock, and existing `Event` object identity.
- Register focused state-boundary regressions once in the aggregate suite.

## Verification

A yielding integer counter makes duplicate ID allocation deterministic with
the unlocked implementation and remains unique once reservation is locked.
Limit regressions cover zero, negative, boolean, and float values without
changing positive filtered reads.
