# Bounded Role-Worker Output Design

**Date:** 2026-08-18  
**Stage:** Phase 11 Worker boundary hardening  
**Status:** Delivered in Iteration 191

## Problem

`RoleWorkerSupervisor` already rejected serialized results larger than its
configured output budget, but `_bounded_json_value()` first called
`json.dumps()` and materialized the entire UTF-8 payload. A large runner result
could therefore consume memory before the Worker boundary applied its 1 MiB
default limit.

## Goals

- Apply the existing output budget while JSON is being encoded.
- Stop as soon as the cumulative UTF-8 bytes exceed the budget.
- Preserve sorted keys, compact separators, `ensure_ascii=False`, `default=str`,
  JSON round-trip normalization, and the existing `_WorkerOutputLimitError`.
- Keep the parent/child protocol, terminal outcomes, and history retention
  unchanged.

## Design

`_bounded_json_value()` now creates a configured `json.JSONEncoder` and consumes
`iterencode()` chunks. It accounts for each chunk's UTF-8 byte length before
retaining it; the first overflow raises the existing bounded error. Only an
already bounded string is joined and decoded with `json.loads()` afterward.

## Acceptance

- The normalizer never calls unbounded `json.dumps()`.
- A first oversized encoder chunk raises without consuming later chunks.
- Existing success normalization, output-limit failure, cancellation, timeout,
  terminal publication, and history tests remain green.

## Non-Goals

This iteration does not change the configured output limit, request validation,
Worker process lifecycle, result schema, or generic orchestrator serializers.
