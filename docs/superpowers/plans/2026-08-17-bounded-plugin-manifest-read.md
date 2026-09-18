# Bounded Plugin Manifest Read Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bound repository Plugin Manifest reads and isolate parser recursion without losing valid siblings.

**Architecture:** Add a 64 KiB limit and one binary reader to `PluginLoader`, then keep parsing and semantic validation in the existing discovery flow. The existing candidate exception boundary gains only the parser recursion failure it can safely contain.

**Tech Stack:** Python 3.10+, standard `pathlib`, `json`, and `unittest`.

## Global Constraints

- `MAX_PLUGIN_MANIFEST_BYTES` is exactly `64 * 1024`.
- Every content read is `MAX_PLUGIN_MANIFEST_BYTES + 1` bytes; no unbounded read API is allowed.
- Existing Manifest schema, runtime support, lifecycle, Broker, and HTTP behavior remain unchanged.
- Work in the current mixed checkout without staging or committing files.

---

### Task 1: Reproduce unbounded and recursive Manifest reads

**Files:**
- Modify: `tests/test_plugin_sdk.py`

**Interfaces:**
- Consumes: `PluginLoader.discover_plugins() -> list[PluginManifest]`
- Produces: two deterministic repository discovery regressions

- [ ] **Step 1: Add an oversized-read regression**

Create a valid Plugin and an oversized sibling. Patch `Path.open` during
discovery so Manifest reads must use binary mode and call `read()` with exactly
`MAX_PLUGIN_MANIFEST_BYTES + 1`; assert only the valid ID is returned.

- [ ] **Step 2: Verify RED**

Run:
`python -m unittest tests.test_plugin_sdk.TestPluginWorkerCoordinator.test_discovery_bounds_manifest_file_reads -v`

Expected: FAIL because `Path.read_text()` opens in text mode and performs an
unbounded read.

- [ ] **Step 3: Add a parser-recursion regression**

Write a within-limit Manifest containing more than Python's recursion limit of
nested arrays, followed alphabetically by a valid Plugin; assert discovery
returns the valid ID.

- [ ] **Step 4: Verify RED**

Run:
`python -m unittest tests.test_plugin_sdk.TestPluginWorkerCoordinator.test_discovery_isolates_recursive_manifest_json -v`

Expected: ERROR with `RecursionError` escaping `discover_plugins()`.

### Task 2: Implement the bounded reader

**Files:**
- Modify: `src/core/kernel/plugin_sdk.py`
- Test: `tests/test_plugin_sdk.py`

**Interfaces:**
- Produces: `MAX_PLUGIN_MANIFEST_BYTES: int`
- Produces: `PluginLoader._read_bounded_manifest(path: Path) -> Any`

- [ ] **Step 1: Add the byte budget and helper**

Define `MAX_PLUGIN_MANIFEST_BYTES = 64 * 1024`. The helper checks
`path.stat().st_size`, reads from `path.open("rb")` with
`MAX_PLUGIN_MANIFEST_BYTES + 1`, rejects oversized bytes with `ValueError`,
then returns `json.loads(raw.decode("utf-8"))`.

- [ ] **Step 2: Route discovery through the helper**

Replace `read_text()` plus direct `json.loads()` with the helper and add
`RecursionError` to the existing per-candidate exception tuple.

- [ ] **Step 3: Verify GREEN**

Run both new tests and the Plugin SDK/installation/runtime/containment suites.
Expected: the new tests pass and all existing Plugin behavior remains green.

### Task 3: Deliver Iteration 183 evidence

**Files:**
- Modify: `AGENTS.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/reports/PROJECT_ANALYSIS.md`
- Modify: `docs/reports/README.md`
- Create: `docs/reports/AUDIT_REPORT_183.md`
- Delete: `docs/reports/AUDIT_REPORT_173.md`

**Interfaces:**
- Consumes: observed verification results
- Produces: rolling audit window 174-183 and current test baseline

- [ ] **Step 1: Run all project gates**

Run aggregate, full discovery, compileall, Ruff, Vitest, Playwright,
typecheck, build, required-services integration, ledger guards, and
`git diff --check`.

- [ ] **Step 2: Update evidence from actual output**

Record only observed counts and outcomes, document the 64 KiB boundary and
candidate isolation, and retain the same-user filesystem/network sandbox
limitation.
