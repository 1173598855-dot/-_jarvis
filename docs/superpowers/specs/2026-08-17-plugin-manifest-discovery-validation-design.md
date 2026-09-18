# Plugin Manifest Discovery Validation Design

**Date:** 2026-08-17
**Iteration:** 182

## Problem

`PluginLoader.discover_plugins()` currently treats successful dataclass
construction as a valid Manifest. Python dataclasses do not enforce annotations,
so repository JSON such as `entry_point: 1`, `permissions: "event_bus"`, or
`sandbox: "false"` enters the discovery result. A missing `plugin_id` also
receives a random compatibility ID, which no longer matches its directory.
Later load calls fail through incidental path/protocol exceptions instead of
keeping the malformed package outside the lifecycle surface.

## Required Behavior

- Repository discovery returns only Manifests whose fields satisfy the local
  typed contract and whose explicit `plugin_id` equals the direct directory
  name.
- Required scalar fields are exact, non-blank strings: `name`, `version`,
  `runtime`, `entry_point`, `api_version`, and `plugin_id`.
- `description` and `author` are exact strings and may be empty.
- `permissions`, `denied_apis`, and `dependencies` are exact lists containing
  only non-empty strings; `sandbox` is an exact boolean.
- Existing dangerous-permission and sandbox-denial checks run during discovery,
  so invalid siblings are logged and skipped without aborting valid siblings.
- Direct `PluginManifest` construction retains its generated-ID compatibility;
  only repository `manifest.json` requires an explicit ID.
- Known legacy and unknown non-empty runtime strings remain discoverable and
  continue to fail closed at the existing load boundary.

## Considered Approaches

1. **Central validation plus a repository parser (selected).** Strengthen the
   existing `_validate_manifest()` and call it from discovery after checking
   the raw explicit ID. This keeps one semantic validator for direct and JSON
   inputs while preserving constructor compatibility.
2. **Validate in `PluginManifest.__post_init__`.** This is compact, but it
   breaks existing direct construction that intentionally generates an ID and
   changes when legacy callers receive errors.
3. **Add a JSON Schema validator.** This gives a declarative contract but adds
   another schema engine and duplicates the already small local validation
   surface.

## Data Flow

For each direct, non-linked Plugin directory, discovery parses a bounded local
JSON object, requires an explicit exact-string ID matching the directory, builds
the dataclass, runs `_validate_manifest()` and `_validate_sandbox_policy()`, and
only then attaches the validated root and publishes the Manifest. Known parse,
type, policy, and filesystem failures remain isolated to that candidate.

## Testing

- Create one valid Plugin and malformed siblings covering missing/mismatched
  IDs, scalar type confusion, string-instead-of-list permissions, non-boolean
  sandbox, malformed list elements, incomplete sandbox policy, and dangerous
  permissions.
- Verify discovery returns only the valid sibling and remains deterministic on
  a second scan.
- Verify direct `_validate_manifest()` rejects representative malformed values
  while valid legacy runtime strings remain accepted for fail-closed loading.

## Scope Boundary

This iteration does not validate entrypoint contents during discovery, change
runtime support, remove direct generated IDs, add archive/HTTP inputs, or create
OS filesystem/network isolation.
