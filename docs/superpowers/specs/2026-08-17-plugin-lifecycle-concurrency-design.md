# Plugin Lifecycle Concurrency Design

**Date:** 2026-08-17
**Iteration:** 181

## Problem

`PluginLoader` owns Worker generations in `_plugins` and `_generations`, but
its public lifecycle methods have no synchronization. Concurrent requests can
both observe a missing Plugin, start separate Workers with conflicting
generations, and overwrite the same registry key. Enable, disable, unload, and
close can likewise interleave state transitions or remove a Worker while
another request still publishes its result.

## Required Behavior

- Discovery, load, enable, disable, unload, close, and registry reads are
  linearized under one loader-owned lifecycle boundary.
- Concurrent exact loads of one Plugin create one Worker generation and return
  the same `PluginInstance`.
- Close cannot race with another lifecycle transition or iterate a dictionary
  being mutated by another request.
- Existing identity checks, error mapping, cleanup order, control-exception
  propagation, and unconfirmed-termination retention remain unchanged.
- No public HTTP, Manifest, Worker protocol, or Broker contract changes.

## Considered Approaches

1. **One reentrant loader lock (selected).** A single `RLock` serializes the
   small lifecycle control plane. Nested `close() -> unload_plugin()` remains
   valid, implementation risk is low, and every shared registry transition has
   one ownership rule. Unrelated Plugin lifecycle requests may wait behind one
   another, but all operations already have bounded deadlines and the current
   repository owns only two Plugins.
2. **Per-Plugin locks.** This allows unrelated Plugins to transition in
   parallel, but lock creation/removal, discovery, close ordering, and retained
   failed generations require an additional synchronized lock registry.
3. **In-flight reservation records.** Publishing transient states could avoid
   holding a lock during Worker I/O, but it expands the public/internal state
   machine and requires waiter cancellation and recovery semantics not needed
   for the current scale.

## Architecture

`PluginLoader` creates one `threading.RLock`. A small method decorator acquires
that lock around each public operation that reads or mutates manifests,
instances, generations, or lifecycle state. The lock is deliberately held
through Worker start/invoke/close so no caller can observe or replace a partial
transition. Internal helpers remain lock-agnostic and are only reached from the
serialized public methods.

## Error And Ownership Semantics

The lock uses `with` ownership, so ordinary exceptions and `BaseException`
control flow always release it. Existing runtime cleanup still runs before a
failed load is published. A Worker whose termination is unconfirmed remains
the only registered generation and continues to block replacement.

## Testing

- A gated runtime makes the first load pause after creation while a second
  thread calls `load_plugin()` with the same Manifest.
- Before the gate opens, exactly one runtime exists and the second caller is
  still waiting.
- After release, both calls return the same instance, only generation 1 exists,
  and loader close reaps that single runtime.
- Existing Plugin SDK, Worker, Broker, installation, protocol, aggregate, and
  full discovery suites remain green.

## Scope Boundary

This iteration does not add per-Plugin parallelism, transient public statuses,
automatic lifecycle retries, new Broker capabilities, or OS filesystem/network
isolation.
