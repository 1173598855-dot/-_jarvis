# Bounded CLI JSON Inputs Design

## Problem

Three local command-line entry points passed unbounded file streams directly
to `json.load()`. A caller controlling the file could force an avoidable large
allocation before any command validation ran.

## Decision

Use one shared `read_bounded_json()` helper with an 8 MiB UTF-8 byte budget.
It checks the current size, reads at most one sentinel byte beyond the budget,
rejects growth, validates UTF-8, and only then calls `json.loads()`.

The helper is used by `agent_factory.py batch`,
`context_compressor.py compress`, and `role_registry.py register`. The public
JSON shapes and command output remain unchanged for in-limit files.

The three scripts bootstrap the repository `src` path when run as files, so
the documented commands do not depend on a caller-provided `PYTHONPATH`.

## Non-Goals

This boundary does not change service HTTP request limits, JSON schema
validation, or the existing role dispatch semantics.
