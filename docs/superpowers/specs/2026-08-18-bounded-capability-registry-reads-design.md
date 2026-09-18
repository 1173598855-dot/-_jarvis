# Bounded Capability Registry Reads Design

**Date:** 2026-08-18
**Iteration:** 184

## Problem

The read-only capability registry advertises 1 MiB per-file and 4 MiB
per-tree limits, but `SKILL.md` and Plugin Manifest content is fully allocated
through `read_text()` or `read_bytes()` before the limit is checked. Tree
hashing also streams until EOF after trusting a pre-open size, so a growing
file can exceed the declared byte budget. Deep Plugin JSON and parser-level
oversized integers raise `RecursionError` or `ValueError` outside the invalid
record boundary and abort the whole snapshot.

## Required Behavior

- Every repository file consumed by capability discovery is opened in binary
  mode and read with the existing 1 MiB limit plus one sentinel byte.
- The stat precheck and post-open sentinel both reject oversized content before
  UTF-8 decoding, JSON parsing, metadata extraction, or hashing.
- Tree totals and digest length fields use the actual bounded bytes read, not a
  stale pre-open file size.
- Deep JSON recursion and parser integer limits produce the existing invalid
  Plugin record while valid siblings and other capability kinds survive.
- Existing capability IDs, records, digests for stable files, risk, health,
  cache, HTTP, and role-tool assembly behavior remain unchanged.

## Approaches

1. **One module-local bounded byte reader (selected).** Route Skill metadata,
   Plugin JSON, and hash content through one helper using the registry's
   existing `_MAX_FILE_BYTES`. This fixes the allocation and growth paths
   without coupling execution discovery to the Plugin SDK.
2. **Post-allocation validation.** Retain `read_text()`/`read_bytes()` and check
   length afterward. This preserves the resource bug and cannot satisfy the
   stated limit.
3. **Reuse `PluginLoader._read_bounded_manifest()`.** This duplicates policy
   concerns across discovery layers, introduces a reverse dependency, and
   would silently reduce the read-only registry contract from 1 MiB to 64 KiB.

## Data Flow

`_read_bounded_file()` checks the current size, opens the path in `rb`, and
reads at most 1,048,577 bytes. It raises the caller-selected stable
`CapabilityValidationError` when either check exceeds the limit. Skill and
Plugin discovery decode only the returned bytes. `_hash_files()` hashes the
same bounded bytes, records their actual length, and applies the existing tree
total. Plugin parser resource failures enter the existing invalid-record path.

## Testing

- Guard all registry file handles so content reads must be binary and use a
  finite size; the existing fixture snapshot must remain identical.
- Underreport an oversized hash target's stat size and verify the sentinel
  rejects it instead of hashing beyond the budget.
- Feed within-limit deeply nested JSON and an over-digit integer to separate
  Plugin candidates; each scan must publish an invalid record and retain the
  valid sibling.
- Run capability/API impact suites, aggregate/discovery, Ruff, compileall,
  frontend gates, and required-services integration.

## Scope Boundary

This iteration does not change Plugin execution discovery's independent 64 KiB
limit, bound directory enumeration or `rglob()` traversal, close same-user path
replacement races, add lifecycle operations, or change HTTP schemas.
