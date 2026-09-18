# Plugin Manifest Discovery Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep malformed repository Plugin Manifests outside the executable lifecycle surface with one strict local validation contract.

**Architecture:** Strengthen `PluginLoader._validate_manifest()` for exact scalar/list types and route discovery through that validator plus repository-only explicit ID/root matching. Candidate failures remain isolated by the existing discovery exception boundary.

**Tech Stack:** Python 3.10+, standard `json`, dataclasses, `unittest`.

## Global Constraints

- Preserve direct `PluginManifest` generated-ID compatibility.
- Preserve discovery of non-empty legacy/unknown runtimes and fail-closed load behavior.
- Do not add dependencies, JSON Schema files, entrypoint execution, or HTTP inputs.

---

### Task 1: Reproduce malformed discovery publication

**Files:**
- Modify: `tests/test_plugin_sdk.py`

**Interfaces:**
- Consumes: `PluginLoader.discover_plugins() -> list[PluginManifest]`
- Produces: deterministic malformed-sibling discovery regression

- [ ] **Step 1: Write malformed sibling fixtures**

Create one valid directory and JSON siblings with missing/mismatched IDs,
wrong scalar/list/boolean types, unsafe permissions, and incomplete denied APIs.
Assert both scans return only the valid Plugin ID.

- [ ] **Step 2: Verify RED**

Run: `python -m unittest tests.test_plugin_sdk.TestPluginWorkerCoordinator.test_discovery_skips_strictly_malformed_manifest_siblings -v`

Expected: FAIL because current dataclass construction publishes multiple
malformed Manifests.

### Task 2: Enforce the typed repository boundary

**Files:**
- Modify: `src/core/kernel/plugin_sdk.py`
- Test: `tests/test_plugin_sdk.py`

**Interfaces:**
- Consumes: parsed manifest mappings and existing `_validate_manifest()` policy
- Produces: `_manifest_from_repository_data(data, root) -> PluginManifest`

- [ ] **Step 1: Implement exact field validation**

Require exact non-blank strings for required scalar fields, exact strings for
optional text, exact lists of non-empty strings for collection fields, exact
boolean sandbox values, valid IDs, and existing dangerous-permission rules.

- [ ] **Step 2: Parse repository data through one helper**

Require raw `plugin_id`, construct the dataclass, run manifest and sandbox
validation, require ID/root equality, attach the root, and return the validated
Manifest. Keep candidate exceptions inside the existing discovery catch list.

- [ ] **Step 3: Verify GREEN and affected behavior**

Run the new regression and Plugin SDK/installation suites. Expected: only valid
siblings are returned; legacy runtime discovery and first-party loading pass.

### Task 3: Deliver Iteration 182 evidence

**Files:**
- Modify: `AGENTS.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/reports/PROJECT_ANALYSIS.md`
- Modify: `docs/reports/README.md`
- Create: `docs/reports/AUDIT_REPORT_182.md`
- Delete: `docs/reports/AUDIT_REPORT_172.md`

**Interfaces:**
- Consumes: final test counts and gate output
- Produces: current Iteration 182 evidence and rolling window 173-182

- [ ] **Step 1: Run complete verification**

Run aggregate, discovery, compileall, Ruff, frontend Vitest/Playwright,
typecheck, build, required-services integration, and `git diff --check`.

- [ ] **Step 2: Update current evidence**

Record only observed results, roll one audit report, and retain the explicit
same-user Worker/OS sandbox limitation.
