# Bounded Worker and Memory Input Reads

**Date:** 2026-08-18
**Iteration:** 194

## Problem

The process-isolated terminal worker decoded all of stdin with `json.load()`.
Writable `MemoryStore` candidate reads used the observed file size as their
limit, and the role worker request protocol accepted prompts of any size.
These paths could allocate unbounded input before policy validation, process
serialization, or Markdown parsing.

## Required Behavior

- Terminal Worker stdin is capped at 32 KiB before UTF-8 decoding and JSON
  parsing.
- Writable MemoryStore entry candidates are capped at 8 MiB while preserving
  regular-file, reparse, descriptor identity, and post-open stability checks.
  Oversized candidates are treated as unreadable; probe deletion must retain
  them.
- `WorkerTaskRequest.prompt` is capped at 32 KiB of UTF-8 before a child
  process is started.
- Existing response shapes, entry parsing, worker lifecycle, and exact-limit
  acceptance remain unchanged.

## Scope Boundary

This iteration does not change HTTP request-body limits, read-only MemoryStore
scan budgets, worker output budgets, or OS-level sandboxing.
