# EventBus Once-Subscription Claim Design

## Context

`EventBus._notify()` currently copies matching subscriptions, releases the
lock, invokes callbacks, and only then removes `once=True` subscriptions.
Concurrent or reentrant emits can therefore copy and invoke the same once
subscription before its first callback returns.

## Decision

- Claim matching once subscriptions by removing them under the subscriber lock
  while building the callback snapshot.
- Invoke all callbacks after releasing the lock.
- Inspect wildcard subscriptions once when the emitted event type itself is
  `"*"`.
- Preserve ordinary subscriptions, callback exception isolation, Event
  identity, history recording, and public method signatures.

## Verification

One deterministic synchronized emit regression holds the first callback open
while other emitters enter. A second regression emits recursively from inside
the once callback. Both must observe exactly one invocation and zero retained
subscriptions afterward.
