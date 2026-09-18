# Bounded Plugin Worker Input Design

## Problem

The child Plugin Worker protocol rejected oversized JSON lines only after
`readline()` had already materialized the complete line. A peer that omitted a
newline could therefore force an avoidable allocation before validation.

## Decision

Read both lifecycle requests and Broker responses with
`MAX_PLUGIN_WORKER_LINE_BYTES + 1`. The existing `decode_message()` remains
the single validator and rejects the sentinel-overflow line with the existing
protocol error. The worker then keeps its current fail-and-exit behavior for
invalid lifecycle input.

## Non-Goals

This change does not alter the wire schema, output limit, broker permissions,
or parent-side subprocess transport policy.
