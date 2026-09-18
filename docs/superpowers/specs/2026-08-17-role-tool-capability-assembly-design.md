# Trusted Role Tool Capability Assembly Design

**Date:** 2026-08-17
**Iteration:** 148
**Status:** Approved for autonomous implementation

## Context

The production role Worker owns a fixed catalog of five read-only model tools:
`system_status`, `model_list`, `orchestrator_status`, `memory_search`, and
`repository_metadata`. Authorization already requires the intersection of the
role declaration, the static grant table, a registered definition, and a local
handler. The general capability registry, however, publishes only Skill,
Plugin, and UI component records and has no assembly relationship with that
catalog.

The next Phase 11 boundary is to make the catalog visible and verifiably
assembled without allowing discovered packages, HTTP input, or public metadata
to become executable tool registrations.

## Decision

Add `role_tool` as a public `CapabilityKind` and publish one healthy, enabled,
verified record for each fixed built-in tool when the trusted implementation
module exists below the repository root. A new immutable catalog contract in
`core.contracts` is the single source for tool IDs, definitions, descriptions,
declared read-only permissions, and deterministic descriptor digests.

The registry validates its role-tool records and produces a small immutable
assembly value containing only:

- schema version `1`;
- the exact sorted built-in capability IDs;
- the deterministic catalog digest.

The parent service serializes that value into the trusted Worker configuration.
The child parses it with strict field and type checks, compares it with its own
static catalog, and only then constructs the fixed broker. No callable, module
path, command, arbitrary tool name, handler configuration, or grant is carried
across the boundary.

## Trust And Authorization Boundaries

- Capability records are descriptive inventory, not authorization grants.
- Only the five source-controlled catalog entries can become Worker tools.
- Skill, Plugin, and UI records never participate in role-tool assembly.
- HTTP requests and task metadata cannot select or add assembled tools.
- Role authorization remains the intersection of `AgentProfile.tools`,
  `READ_ONLY_ROLE_TOOLS`, registered definitions, and process-local handlers.
- `AgentFactory` without an explicitly supplied broker keeps an empty broker.
- The existing non-production in-process role path therefore gains no tools.
- Handlers continue to capture only trusted process-local dependencies and keep
  existing budgets, redaction, bounded reads, and audit behavior.

## Components And Data Flow

### Immutable Catalog

`src/core/contracts/role_tool_catalog.py` defines frozen catalog entries and a
strict `RoleToolAssembly` wire value. Descriptor hashes use canonical JSON over
the capability ID, tool name, description, parameter schema, and declared
permissions. Catalog construction rejects duplicate IDs or tool names.

### Capability Registry

`CapabilityRegistry.snapshot()` adds built-in records after repository-local
Skill, Plugin, and UI discovery. It publishes role-tool records only when
`src/core/brain/read_only_role_tools.py` is a regular, non-symlink file below
the trusted repository root. The record points to that relative source file,
uses `enabled` lifecycle, low risk, healthy status, verified provenance, and
the catalog entry digest.

`CapabilityRegistry.role_tool_assembly()` checks only the role-tool portion of
the snapshot. It rejects missing or extra IDs, duplicate-record issues,
non-enabled lifecycle, non-healthy health, non-low risk, non-verified
provenance, and descriptor digest mismatches before returning evidence.
Unrelated degraded Skill or Plugin records do not disable the built-in tools.

### Parent And Worker

Both Python service constructors create or accept the capability registry
before creating the default role supervisor. They pass
`registry.role_tool_assembly().to_dict()` in the supervisor's trusted runner
configuration. Injected supervisors preserve their existing ownership and do
not force an unused assembly operation.

`execute_role_task()` requires and strictly parses `role_tool_assembly` before
creating the broker. `create_read_only_role_tool_broker()` verifies the exact
assembly against the local immutable catalog and uses the catalog's definitions
instead of maintaining a second inline definition table.

## Fail-Closed Behavior

Assembly fails before model dispatch when any of these conditions holds:

- the evidence is absent, contains unknown fields, has invalid JSON types, or
  uses another schema version;
- capability IDs are missing, duplicated, reordered, or contain an unknown ID;
- the catalog digest differs from the local static catalog;
- registry role-tool records are missing, duplicated, disabled, invalid,
  degraded, higher than low risk, unverified, or have a mismatched digest;
- the trusted role-tool implementation source is absent or symlinked.

The failure does not fall back to an unverified broker or to request-provided
tool names. Existing Worker error normalization and secret redaction remain in
force.

## Public Contract

The capability API query enum, capability ID pattern, OpenAPI record enum,
frontend `CapabilityKind`, summary counts, label, and icon add `role_tool`.
The Plugins view remains read-only for these records; it gains no lifecycle or
execution action. The capability schema version remains `1` because the record
shape is unchanged and the kind enum is additive.

## Compatibility And Scope

- Preserve all existing Skill, Plugin, UI, role dispatch, result, and audit
  shapes except for the additive capability kind and five additional records.
- Do not load handlers through the capability registry.
- Do not accept package paths, archives, URLs, manifests, or lifecycle writes.
- Do not expand the fixed five-tool catalog or any role grant in this iteration.
- Do not add OS-level filesystem or network isolation.
- Do not give the general in-process `AgentFactory` a production tool broker.

## Test Strategy

1. Prove catalog and assembly values are immutable, deterministic, strict, and
   reject missing, extra, duplicate, reordered, or mismatched evidence.
2. Prove registry snapshots publish the five records without importing or
   executing handlers and that assembly rejects unhealthy variants.
3. Prove broker creation requires valid assembly and preserves the existing
   role/grant/definition/handler intersection.
4. Prove both service constructors pass registry-owned evidence and the child
   rejects absent or invalid evidence before factory execution.
5. Extend OpenAPI and frontend tests for the additive public kind.
6. Run targeted suites, aggregate and discovery suites, compileall, Ruff
   comparison, Vitest, Playwright, typecheck, build, local integration, and
   whitespace validation.

## Exit Criteria

- The public snapshot truthfully includes five built-in role-tool records.
- The default role Worker cannot start its tool broker without exact registry
  assembly evidence matching its local static catalog.
- Public records cannot introduce a handler or grant execution permission.
- Existing role tool budgets, redaction, bounded operations, and audit evidence
  remain green.
- All relevant backend, contract, frontend, and integration gates have fresh
  passing evidence or a precisely documented unrelated baseline.
