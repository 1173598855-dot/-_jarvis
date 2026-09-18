# Capability Registry And Safe Deployment Design

**Date:** 2026-07-28

**Target:** Stage D of `docs/DEVELOPMENT_GUIDE.md`, delivered as Iterations 135-139.

## Goal

Build a local-first capability registry for Skills, Plugins, and UI components,
then add a content-addressed package store that can verify, install, upgrade,
roll back, remove, and rebuild capabilities without executing package content.
Expose only read-only registry data through the existing three-service API and
the Plugins view.

## Scope

The batch includes:

- deterministic discovery of repository-local Skills, Plugins, and UI components;
- a versioned record schema with lifecycle, compatibility, provenance, health,
  permissions, risk, and a content digest;
- deterministic local query scoring with compatibility and risk filters;
- verification of ZIP capability bundles supplied as trusted local bytes;
- content-addressed storage and atomic lifecycle state for install, upgrade,
  rollback, removal, and rebuild;
- a shared read-only registry API and an operational UI view of origin,
  permissions, compatibility, health, and risk.

The batch excludes:

- network download, marketplace search, or URL fetching;
- HTTP endpoints that accept archives, filesystem paths, or lifecycle mutations;
- loading or executing installed package code;
- Plugin process isolation and runtime brokers, which remain Stage E work;
- automatic enablement. Every imported capability is `disabled`.

## Architecture

`capability_manifest.py` owns immutable value objects and validation.
`capability_registry.py` discovers only direct children of configured trusted
roots and publishes a sorted snapshot. Discovery never imports Python or runs
package scripts. `capability_resolver.py` ranks records using explicit, bounded
query inputs and deterministic tie-breaking.

`file_capability_store.py` is the filesystem adapter. It verifies the caller's
expected SHA-256 before parsing a ZIP, rejects traversal, absolute paths,
symlinks, encrypted entries, duplicates, excessive entry counts, and excessive
compressed or uncompressed size. It requires one root `capability.json` and a
`payload/` tree. Accepted bundles are copied into a content-addressed revision
directory and recorded by an atomically replaced JSON index. Package content is
never imported or executed.

The HTTP adapters construct registry responses from explicit public
serialization. Python HTTPServer and FastAPI provide the canonical endpoint;
Express proxies it through the existing Core API bridge. No endpoint exposes
absolute paths. The Solid.js view renders strings as text through normal JSX and
does not introduce HTML injection sinks.

## Record Contract

Every public record has these fields:

- `schema_version`: integer `1`;
- `capability_id`: `<kind>:<name>` using lowercase ASCII identifiers;
- `kind`: `skill`, `plugin`, or `ui_component`;
- `name`, `description`, and nullable `version`;
- `relative_path` and nullable `entrypoint`, both repository-relative POSIX paths;
- `lifecycle`: `discovered`, `disabled`, `enabled`, or `invalid`;
- `permissions`: sorted unique strings;
- `compatibility`: declared API/runtime constraints and a computed status;
- `provenance`: source URL, license, SHA-256, and completeness status;
- `health`: `healthy`, `degraded`, or `invalid`, plus stable issue codes;
- `risk`: `low`, `medium`, or `high`, plus stable reason codes.

Unknown source, license, or version stays `null`; the registry does not invent
metadata. A deterministic tree digest is still computed for every readable,
non-symlink local capability.

## Discovery Rules

- Skill roots accept direct child directories containing `SKILL.md`.
- Plugin roots accept direct child directories containing valid `manifest.json`.
- UI roots accept direct `.tsx` files and direct child directories whose public
  entrypoint is `index.ts` or `index.tsx`.
- Discovery does not follow symlinks and reports invalid or unreadable entries
  as bounded issue records rather than leaving the trusted root.
- Generated files, `__pycache__`, virtual environments, `node_modules`, hidden
  test output, and build output do not contribute to a digest.
- Plugin metadata comes from `manifest.json`; Skill source/license metadata may
  be read from the established Markdown labels; UI components remain local with
  unknown external provenance unless a future manifest declares it.

## Resolution

The resolver accepts `query`, optional `kind`, `compatible_only`,
`max_risk`, and `limit` in `1..100`. It tokenizes bounded ASCII/Unicode text,
scores exact ID/name matches above prefix and description matches, then adds
small bonuses for healthy, compatible, and complete-provenance records. It
sorts by descending score and ascending capability ID so repeated scans are
stable. Filtering happens before scoring.

## Package And Lifecycle Rules

The external caller supplies bundle bytes and an expected 64-character SHA-256.
The root `capability.json` declares schema version, stable ID, kind, version,
description, HTTPS source URL, SPDX-style allowlisted license, relative
entrypoint, permissions, and compatibility. Allowed licenses are
`MIT`, `Apache-2.0`, `BSD-2-Clause`, and `BSD-3-Clause`.

Installation creates an immutable revision and a disabled state entry. Upgrade
adds a revision and switches the selected revision only after validation and
publication succeed. Rollback switches to an already verified earlier revision.
Removal deletes only a canonical revision selected from authenticated local
state; complete uninstall removes the capability only after no revision remains.
Rebuild re-hashes and re-validates stored content and fails closed on drift.

The store rejects duplicate `(capability_id, version, digest)` publication only
when metadata differs; exact retries are idempotent. It serializes in-process
writers with a lock and uses temporary files plus `os.replace` for state.

## Error Handling

Domain validation raises stable `CapabilityValidationError` codes. Store
operations raise `CapabilityStoreError` codes without embedding archive content,
absolute paths, environment values, or exception traces. Discovery converts
entry-local failures into issue codes and continues; failure to establish a
trusted root fails the whole snapshot.

The read-only API returns the existing `ErrorResponse` shape for invalid query
parameters, Core API unavailability, and registry failures. Express preserves
Core status and body through the existing proxy boundary.

## Testing

Each iteration follows red-green-refactor:

1. schema and discovery fixtures, including symlink and malformed metadata;
2. deterministic resolver scoring and filter boundaries;
3. malicious archive fixtures for traversal, symlinks, duplicates, size limits,
   digest mismatch, unsupported license, and valid disabled installation;
4. upgrade, idempotent retry, rollback, remove, drift detection, and rebuild;
5. three-service OpenAPI shape checks, Express proxy tests, Solid.js rendering,
   typecheck, production build, and Playwright screenshots.

The final gate is the repository's aggregate and discovery Python suites,
compileall, Vitest, Playwright, TypeScript typecheck, Vite build, deterministic
local integration profile, and `git diff --check`.

## Delivery Sequence

- Iteration 135: schema and local discovery.
- Iteration 136: compatibility evaluation and local resolver.
- Iteration 137: package verification and disabled content-addressed install.
- Iteration 138: upgrade, rollback, removal, and rebuild.
- Iteration 139: read-only API, OpenAPI contract, Plugins view, and Stage D gate.

Each iteration updates the rolling audit ledger and current project analysis,
then creates a path-scoped commit before the next iteration begins.
