# Capability Registry And Safe Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete Stage D with a local-first registry, deterministic resolver,
verified disabled package store, reversible lifecycle, and read-only API/UI.

**Architecture:** Immutable domain records and filesystem discovery live under
`src/core/kernel`; content-addressed persistence lives in an adapter. HTTP
adapters expose public serialization only, and Express continues to bridge Core
API behavior. Package content is validated but never imported or executed.

**Tech Stack:** Python 3.10+ standard library, unittest, FastAPI, Express 5,
Solid.js, TypeScript, Vitest, Playwright, OpenAPI 3.1.

## Global Constraints

- No new dependency, network fetch, arbitrary filesystem path, or automatic enablement.
- Only `MIT`, `Apache-2.0`, `BSD-2-Clause`, and `BSD-3-Clause` package licenses pass.
- Public paths are repository-relative POSIX paths; absolute paths never leave Core.
- Archive entry count, compressed bytes, uncompressed bytes, and per-file bytes are bounded.
- Tests precede production changes and must be observed failing for the intended reason.
- Each iteration updates `CHANGELOG.md`, `docs/reports/PROJECT_ANALYSIS.md`,
  `docs/reports/README.md`, and its rolling `AUDIT_REPORT_<N>.md`.

---

### Task 1: Iteration 135 - Versioned Capability Records And Discovery

**Files:**
- Create: `src/core/kernel/capability_manifest.py`
- Create: `src/core/kernel/capability_registry.py`
- Create: `tests/test_capability_registry.py`
- Modify: `tests/run_all.py`
- Modify: `tests/test_run_all_coverage.py`
- Modify: iteration ledger and current project documentation

**Interfaces:**
- Produces: `CapabilityKind`, `CapabilityLifecycle`, `CapabilityRecord`,
  `CapabilitySnapshot`, `CapabilityValidationError`.
- Produces: `CapabilityRegistry(root: Path).snapshot() -> CapabilitySnapshot`.
- Public serialization: `record.to_public_dict() -> dict[str, object]`.

- [ ] **Step 1: Write failing schema tests**

```python
def test_public_record_uses_relative_paths_and_explicit_unknown_metadata(self):
    record = make_record(relative_path="skills/example", version=None)
    body = record.to_public_dict()
    self.assertEqual(body["schema_version"], 1)
    self.assertEqual(body["relative_path"], "skills/example")
    self.assertIsNone(body["version"])
    self.assertNotIn(str(self.root), json.dumps(body))
```

- [ ] **Step 2: Run the schema test and verify RED**

Run: `python -m unittest tests.test_capability_registry -v`

Expected: import failure because `capability_manifest` does not exist.

- [ ] **Step 3: Implement immutable records and strict identifier/path validation**

Implement enums and frozen dataclasses. Reject absolute paths, `..`, backslashes,
control characters, invalid identifiers, unsupported lifecycle values, duplicate
permissions, and unbounded public strings. Serialize only declared public fields.

- [ ] **Step 4: Write failing discovery tests**

```python
def test_snapshot_discovers_skills_plugins_and_ui_without_importing_code(self):
    snapshot = CapabilityRegistry(self.root).snapshot()
    self.assertEqual(
        [record.capability_id for record in snapshot.records],
        ["plugin:event-logger", "skill:memory-keeper", "ui_component:StatusIndicator"],
    )
    self.assertFalse(self.import_marker.exists())
```

Cover malformed JSON, missing fields, symlinked entries, ignored generated
directories, deterministic SHA-256, unknown provenance, and stable sorting.

- [ ] **Step 5: Run discovery tests and verify RED**

Run: `python -m unittest tests.test_capability_registry -v`

Expected: missing `CapabilityRegistry` or assertion failure for absent records.

- [ ] **Step 6: Implement bounded read-only discovery**

Scan only configured direct children with `Path.iterdir()`, reject symlinks,
parse JSON with the standard library, parse established Skill labels without
executing Markdown, and hash a sorted list of safe regular files.

- [ ] **Step 7: Verify GREEN and register the suite exactly once**

Run: `python -m unittest tests.test_capability_registry tests.test_run_all_coverage -v`

Expected: all tests pass and the aggregate coverage guard names the suite once.

- [ ] **Step 8: Update Iteration 135 evidence and commit**

```powershell
git add src/core/kernel/capability_manifest.py src/core/kernel/capability_registry.py tests/test_capability_registry.py tests/run_all.py tests/test_run_all_coverage.py CHANGELOG.md docs/reports/PROJECT_ANALYSIS.md docs/reports/README.md docs/reports/AUDIT_REPORT_135.md docs/reports/AUDIT_REPORT_125.md
git commit -m "feat(capabilities): add local capability registry"
```

### Task 2: Iteration 136 - Compatibility And Deterministic Resolution

**Files:**
- Create: `src/core/kernel/capability_resolver.py`
- Create: `tests/test_capability_resolver.py`
- Modify: `src/core/kernel/capability_manifest.py`
- Modify: `src/core/kernel/capability_registry.py`
- Modify: aggregate tests and iteration documentation

**Interfaces:**
- Produces: `CompatibilityTarget(jarvis_api, python, node)`.
- Produces: `CapabilityQuery(query, kind, compatible_only, max_risk, limit)`.
- Produces: `CapabilityMatch(record, score, reasons)`.
- Produces: `CapabilityResolver.resolve(snapshot, query, target) -> tuple[CapabilityMatch, ...]`.

- [ ] **Step 1: Write failing compatibility tests**

```python
def test_incompatible_runtime_is_explicit_and_filterable(self):
    snapshot = snapshot_with(python_constraint=">=99")
    matches = self.resolver.resolve(
        snapshot,
        CapabilityQuery(query="memory", compatible_only=True),
        CompatibilityTarget(python="3.13.5", node="22.0.0", jarvis_api="1.0.0"),
    )
    self.assertEqual(matches, ())
```

- [ ] **Step 2: Run resolver tests and verify RED**

Run: `python -m unittest tests.test_capability_resolver -v`

Expected: import failure because `capability_resolver` does not exist.

- [ ] **Step 3: Implement the bounded compatibility grammar**

Support exact versions plus comma-separated `>=`, `>`, `<=`, `<`, `==`
comparators over numeric dot versions. Reject wildcards, prerelease syntax,
unknown operators, more than eight clauses, and components outside `0..999999`.

- [ ] **Step 4: Write failing ranking and validation tests**

```python
def test_exact_name_beats_description_and_ties_use_capability_id(self):
    matches = self.resolver.resolve(self.snapshot, CapabilityQuery(query="logger"), self.target)
    self.assertEqual(matches[0].record.capability_id, "plugin:logger")
    self.assertGreater(matches[0].score, matches[1].score)
```

Cover query length, limit `1..100`, kind/risk filters, Unicode tokenization,
stable tie-breaking, reason ordering, and empty-query inventory ordering.

- [ ] **Step 5: Implement resolution and verify GREEN**

Run: `python -m unittest tests.test_capability_registry tests.test_capability_resolver -v`

Expected: all registry and resolver tests pass.

- [ ] **Step 6: Update Iteration 136 evidence and commit**

```powershell
git add src/core/kernel/capability_manifest.py src/core/kernel/capability_registry.py src/core/kernel/capability_resolver.py tests/test_capability_resolver.py tests/run_all.py tests/test_run_all_coverage.py CHANGELOG.md docs/reports/PROJECT_ANALYSIS.md docs/reports/README.md docs/reports/AUDIT_REPORT_136.md docs/reports/AUDIT_REPORT_126.md
git commit -m "feat(capabilities): add deterministic local resolution"
```

### Task 3: Iteration 137 - Verified Disabled Package Installation

**Files:**
- Create: `src/adapters/file_capability_store.py`
- Create: `tests/test_file_capability_store.py`
- Modify: `.gitignore`
- Modify: aggregate tests and iteration documentation

**Interfaces:**
- Produces: `CapabilityPackageLimits(max_archive_bytes, max_files,
  max_file_bytes, max_uncompressed_bytes)`.
- Produces: `CapabilityStoreError(code: str, message: str)`.
- Produces: `InstalledCapability` public state record.
- Produces: `FileCapabilityStore(root, limits).install(bundle: bytes,
  expected_sha256: str) -> InstalledCapability`.

- [ ] **Step 1: Write malicious archive tests before the store exists**

```python
def test_install_rejects_traversal_before_writing_payload(self):
    bundle = zip_bytes({"capability.json": valid_manifest(), "../escape.py": b"x"})
    with self.assertRaisesRegex(CapabilityStoreError, "ARCHIVE_PATH_INVALID"):
        self.store.install(bundle, sha256(bundle).hexdigest())
    self.assertFalse((self.temp_root.parent / "escape.py").exists())
```

Cover absolute paths, drive paths, backslashes, symlinks, encrypted entries,
duplicates, missing manifest, non-UTF-8 names, file count, compressed size,
per-file size, total expanded size, digest mismatch, invalid source URL,
unsupported license, and invalid entrypoint.

- [ ] **Step 2: Run package tests and verify RED**

Run: `python -m unittest tests.test_file_capability_store -v`

Expected: import failure because `file_capability_store` does not exist.

- [ ] **Step 3: Implement streaming verification and immutable publication**

Hash input first, enforce compressed size before opening, inspect every
`ZipInfo`, stream each regular file through byte counters and SHA-256, require
`capability.json` plus `payload/`, and publish with a temporary sibling followed
by `os.replace`. Do not call `extractall`, import modules, or spawn processes.

- [ ] **Step 4: Write the valid-install and idempotency tests**

```python
def test_valid_package_installs_disabled_and_exact_retry_is_idempotent(self):
    first = self.store.install(self.bundle, self.digest)
    second = self.store.install(self.bundle, self.digest)
    self.assertEqual(first, second)
    self.assertEqual(first.lifecycle, CapabilityLifecycle.DISABLED)
    self.assertEqual(len(self.store.list_revisions(first.capability_id)), 1)
```

- [ ] **Step 5: Verify GREEN and run focused security regression**

Run: `python -m unittest tests.test_file_capability_store tests.test_capability_registry -v`

Expected: all tests pass and no archive fixture writes outside the temp root.

- [ ] **Step 6: Update Iteration 137 evidence and commit**

```powershell
git add .gitignore src/adapters/file_capability_store.py tests/test_file_capability_store.py tests/run_all.py tests/test_run_all_coverage.py CHANGELOG.md docs/reports/PROJECT_ANALYSIS.md docs/reports/README.md docs/reports/AUDIT_REPORT_137.md docs/reports/AUDIT_REPORT_127.md
git commit -m "feat(capabilities): verify and stage disabled packages"
```

### Task 4: Iteration 138 - Reversible Capability Lifecycle

**Files:**
- Modify: `src/adapters/file_capability_store.py`
- Modify: `tests/test_file_capability_store.py`
- Modify: iteration documentation

**Interfaces:**
- Produces: `upgrade(bundle, expected_sha256) -> InstalledCapability`.
- Produces: `rollback(capability_id, revision_id=None) -> InstalledCapability`.
- Produces: `remove(capability_id, revision_id=None) -> bool`.
- Produces: `rebuild(capability_id) -> InstalledCapability`.

- [ ] **Step 1: Write failing lifecycle tests**

```python
def test_upgrade_switches_only_after_publication_and_rollback_restores_previous(self):
    v1 = self.store.install(self.bundle_v1, self.digest_v1)
    v2 = self.store.upgrade(self.bundle_v2, self.digest_v2)
    self.assertNotEqual(v1.revision_id, v2.revision_id)
    restored = self.store.rollback(v1.capability_id)
    self.assertEqual(restored.revision_id, v1.revision_id)
    self.assertEqual(restored.lifecycle, CapabilityLifecycle.DISABLED)
```

Cover failed-upgrade pointer preservation, explicit rollback target validation,
last-revision removal, exact retry, state corruption, payload drift, rebuild
after restart, concurrent writers, and unknown content preservation.

- [ ] **Step 2: Run lifecycle tests and verify RED**

Run: `python -m unittest tests.test_file_capability_store -v`

Expected: missing lifecycle methods or assertions showing no revision switch.

- [ ] **Step 3: Implement atomic lifecycle state**

Keep immutable revisions, a selected revision ID, and bounded history in one
versioned index. Hold a shared per-root `threading.RLock`, re-read state before
publication, write canonical JSON to a temporary sibling, fsync file content,
then `os.replace`. Resolve every deletion target from validated state and verify
it remains under the canonical store root before removal.

- [ ] **Step 4: Implement rebuild and fail-closed drift detection**

Recompute manifest and payload digests without executing content. Preserve
unknown files, reject state/payload disagreement, and never mark a drifted
revision selected or enabled.

- [ ] **Step 5: Verify GREEN**

Run: `python -m unittest tests.test_file_capability_store -v`

Expected: all install and lifecycle cases pass.

- [ ] **Step 6: Update Iteration 138 evidence and commit**

```powershell
git add src/adapters/file_capability_store.py tests/test_file_capability_store.py CHANGELOG.md docs/reports/PROJECT_ANALYSIS.md docs/reports/README.md docs/reports/AUDIT_REPORT_138.md docs/reports/AUDIT_REPORT_128.md
git commit -m "feat(capabilities): add reversible package lifecycle"
```

### Task 5: Iteration 139 - Read-Only Contract And Plugins View

**Files:**
- Modify: `src/main.py`
- Modify: `src/main_fastapi.py`
- Modify: `frontend/server.js`
- Modify: `contracts/core-api.openapi.json`
- Modify: `frontend/src/types/api.ts`
- Modify: `frontend/src/services/jarvis-api.ts`
- Modify: `frontend/src/views/PluginsView.tsx`
- Modify: relevant Python, Vitest, and Playwright tests
- Modify: project documentation and rolling audit ledger

**Interfaces:**
- Adds: `GET /api/capabilities/registry`.
- Query: `q`, `kind`, `compatible_only`, `max_risk`, `limit`.
- Response: `{schema_version: 1, capabilities: CapabilityRecord[], count: int}`.
- Errors: existing `ErrorResponse` with `INVALID_REQUEST`,
  `CAPABILITY_REGISTRY_UNAVAILABLE`, or Express Core proxy errors.

- [ ] **Step 1: Write failing OpenAPI and Python adapter tests**

```python
def test_capability_registry_path_is_read_only_and_schema_bound(self):
    operation = self.spec["paths"]["/api/capabilities/registry"]["get"]
    self.assertEqual(operation["operationId"], "listCapabilities")
    self.assertNotIn("post", self.spec["paths"]["/api/capabilities/registry"])
```

Assert query bounds, no absolute path leakage, stable error codes, and matching
schemas from Python HTTPServer and FastAPI fixtures.

- [ ] **Step 2: Run contract tests and verify RED**

Run: `python -m unittest tests.test_api_contract tests.test_main tests.test_main_fastapi -v`

Expected: missing OpenAPI path and 404 adapter responses.

- [ ] **Step 3: Implement Python routes and explicit public response shaping**

Construct `CapabilityQuery` only from validated scalar parameters. Reject arrays,
unknown enum values, invalid booleans, overlong query strings, and limits outside
`1..100`. Run read-only discovery without accepting a caller-controlled root.

- [ ] **Step 4: Write failing Express proxy tests, then implement the proxy**

```javascript
test('proxies the read-only capability registry query unchanged', async () => {
  const response = await fetch(`${base}/api/capabilities/registry?q=memory&limit=5`);
  expect(response.status).toBe(200);
  expect(coreCapabilityUrl).toBe('/api/capabilities/registry?q=memory&limit=5');
});
```

Use the existing Core proxy helper and preserve status/error envelopes. Do not
add a local archive or lifecycle route to Express.

- [ ] **Step 5: Write failing Solid.js view tests**

Assert capability kind counts, provenance state, compatibility, health, risk,
permissions, loading/degraded/empty states, and no lifecycle buttons for Skill
or UI records. Keep existing Plugin lifecycle actions unchanged.

- [ ] **Step 6: Implement typed client and Plugins view integration**

Add strict TypeScript interfaces and a polling resource gated by Core
availability. Render metadata in the existing flat plugin/tool list with Lucide
icons and existing status indicators. Use JSX text nodes only.

- [ ] **Step 7: Run focused GREEN gates**

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_api_contract tests.test_main tests.test_main_fastapi -v
Set-Location frontend
npm test -- --run
npm run typecheck
npm run build
```

Expected: all focused Python and frontend gates pass.

- [ ] **Step 8: Verify browser layout**

Run: `cd frontend; npm run test:e2e`

Expected: capability metadata is visible without text overlap at desktop and
390px mobile viewports; existing six-view navigation remains green.

- [ ] **Step 9: Run the Stage D final gate**

```powershell
.\venv\Scripts\python.exe tests/run_all.py
.\venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
.\venv\Scripts\python.exe -m compileall -q src tests scripts
Set-Location frontend
npm test -- --run
npm run test:e2e
npm run typecheck
npm run build
Set-Location ..
.\venv\Scripts\python.exe scripts/ci_local_integration.py --require-services
git diff --check
```

- [ ] **Step 10: Update Iteration 139 evidence and commit**

```powershell
git add src/main.py src/main_fastapi.py frontend/server.js contracts/core-api.openapi.json frontend/src/types/api.ts frontend/src/services/jarvis-api.ts frontend/src/views/PluginsView.tsx tests frontend/src/tests frontend/e2e README.md AGENTS.md CHANGELOG.md docs/DEVELOPMENT_GUIDE.md docs/reports/PROJECT_ANALYSIS.md docs/reports/README.md docs/reports/AUDIT_REPORT_139.md docs/reports/AUDIT_REPORT_129.md
git commit -m "feat(capabilities): expose verified registry metadata"
```

## Plan Self-Review

- Every design requirement maps to one of Tasks 1-5.
- Runtime execution and remote download remain explicitly outside scope.
- Domain names and method signatures are consistent across producing and consuming tasks.
- Every production behavior has a preceding failing test and an exact verification command.
- No task contains unresolved placeholders or grants caller-controlled paths, commands, or URLs.
