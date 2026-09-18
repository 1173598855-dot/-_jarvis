# Bounded Plugin Manifest Read Design

**Date:** 2026-08-17
**Iteration:** 183

## Problem

`PluginLoader.discover_plugins()` reads each repository `manifest.json` with
unbounded `Path.read_text()`. A local malformed package can therefore allocate
an arbitrarily large string before the strict Manifest validator runs. JSON
nested beyond Python's parser recursion limit also raises `RecursionError`,
which currently escapes the candidate boundary and prevents valid later
siblings from being discovered.

## Required Behavior

- Read at most 64 KiB plus one sentinel byte from each Plugin Manifest.
- Reject files whose pre-open size or bounded read exceeds 64 KiB.
- Decode UTF-8 and parse JSON only after the byte limit is established.
- Isolate JSON parser recursion failure to the malformed candidate, preserving
  deterministic discovery of valid siblings.
- Keep the Iteration 182 field, ID, sandbox, dangerous-permission, and runtime
  semantics unchanged.

## Approaches

1. **Local bounded binary reader (selected).** Add one Plugin-specific limit
   and helper in `plugin_sdk.py`, using a size precheck plus `read(limit + 1)`.
   This bounds both the normal path and file-growth race with minimal impact.
2. **Post-read size validation.** Simpler, but the unbounded allocation has
   already happened and therefore does not solve the resource boundary.
3. **Shared repository reader refactor.** Could later align all discovery
   surfaces, but coupling Plugin execution discovery to the broader capability
   scanner expands the blast radius without improving this iteration's exit
   condition.

## Data Flow

For each direct non-reparse Plugin directory, discovery confirms a regular
Manifest path, checks its reported size, opens it in binary mode, reads no more
than 65,537 bytes, and rejects an oversized result. Only bounded bytes are
decoded and passed to `json.loads()`. Existing object and semantic validation
then runs before the root is attached or the Manifest is published.

## Testing

- Guard the file API so every Manifest content read must be binary and use the
  exact `limit + 1` size; verify an oversized sibling is skipped and a valid
  sibling remains discoverable.
- Create a within-limit deeply nested JSON sibling that raises parser
  recursion; verify it is isolated and a valid sibling remains discoverable.
- Run Plugin suites, aggregate/discovery, Ruff, compileall, frontend gates, and
  required-services integration.

## Scope Boundary

This iteration does not add archive or HTTP inputs, change the 1 MiB read-only
capability scanner limit, validate entrypoint contents during discovery, close
same-user path replacement races, or provide filesystem/network isolation.
