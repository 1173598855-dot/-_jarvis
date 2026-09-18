# Trusted Role Tool Capability Assembly Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish the fixed five read-only role tools in the general capability registry and require exact registry-owned assembly evidence before a production role Worker can bind their local handlers.

**Architecture:** A new immutable contracts-layer catalog owns tool metadata, definitions, descriptor hashes, and a strict JSON-safe `RoleToolAssembly` value. `CapabilityRegistry` maps those static entries to public `role_tool` records and validates them into evidence; service-owned Workers receive only exact IDs and a digest, then verify them against the same local catalog before creating the unchanged fixed handler broker.

**Tech Stack:** Python 3.10+ dataclasses and standard-library hashing/JSON, existing capability manifest and role-tool protocol, `unittest`, Solid.js/TypeScript, OpenAPI JSON.

## Global Constraints

- Capability records describe inventory and never authorize or load handlers.
- The Worker accepts no callable, path, command, arbitrary tool name, handler mapping, or role grant in assembly evidence.
- The exact fixed catalog remains `system_status`, `model_list`, `orchestrator_status`, `memory_search`, and `repository_metadata`.
- Preserve the existing role declaration, static grant, definition, and handler intersection plus all budgets, bounds, redaction, and audit behavior.
- Preserve the empty default broker for `AgentFactory` instances without an explicit production broker.
- Keep capability schema version `1`; add `role_tool` as an additive kind.
- Preserve all unrelated staged and unstaged work; do not commit, stage, reset, clean, or rewrite user changes.
- Compare Ruff with the known 152-finding baseline instead of expanding this iteration into workspace-wide lint cleanup.

---

### Task 1: Define the immutable catalog and assembly protocol

**Files:**
- Create: `src/core/contracts/role_tool_catalog.py`
- Create: `tests/test_role_tool_catalog.py`
- Modify: `tests/run_all.py`
- Modify: `tests/test_run_all_coverage.py`

**Interfaces:**
- Produces: `ROLE_TOOL_CATALOG`, `RoleToolCatalogEntry`, `RoleToolAssembly.from_value()`, `RoleToolAssembly.for_catalog()`, `role_tool_catalog_digest()`, and `role_tool_definitions()`.
- Consumes: `RoleToolDefinition`, `RoleToolProtocolError`, and `stable_json_bytes()` from `core.contracts.role_tool_protocol`.

- [x] **Step 1: Write strict catalog and assembly tests**

Add tests that assert the exact five tool names and IDs, immutable parameter schemas, deterministic 64-character lowercase descriptor/catalog hashes, canonical sorted IDs, and JSON round-tripping. Add table-driven failures for absent/extra fields, booleans as schema versions, non-list IDs, duplicates, reversed order, unknown IDs, invalid hashes, and digest mismatch.

- [x] **Step 2: Run the new suite and verify RED**

Run: `.\venv\Scripts\python.exe -m unittest tests.test_role_tool_catalog -v`

Expected: import failure because `core.contracts.role_tool_catalog` does not exist.

- [x] **Step 3: Implement the minimal immutable contract**

Create frozen, slotted catalog entries with `capability_id`, `definition`, and sorted unique `permissions`. Construct the exact definitions currently owned by `_definitions()` in `read_only_role_tools.py`. Hash canonical descriptor dictionaries with SHA-256. Implement a frozen assembly with exact fields `schema_version`, `capability_ids`, and `catalog_sha256`; reject unknown fields and require an exact sorted match to the static catalog when constructing trusted evidence.

- [x] **Step 4: Run catalog tests and aggregate registration checks**

Run: `.\venv\Scripts\python.exe -m unittest tests.test_role_tool_catalog tests.test_run_all_coverage -v`

Expected: all selected tests pass and the new test case occurs once in the aggregate list.

### Task 2: Publish and validate role-tool capability records

**Files:**
- Modify: `src/core/kernel/capability_manifest.py`
- Modify: `src/core/kernel/capability_registry.py`
- Modify: `tests/test_capability_registry.py`
- Modify: `tests/test_capability_resolver.py`

**Interfaces:**
- Consumes: immutable catalog entries and `RoleToolAssembly.for_catalog()` from Task 1.
- Produces: `CapabilityKind.ROLE_TOOL` and `CapabilityRegistry.role_tool_assembly() -> RoleToolAssembly`.

- [x] **Step 1: Add failing public-record and fail-closed assembly tests**

Use a fixture repository containing a regular
`src/core/brain/read_only_role_tools.py`. Assert exactly five sorted
`role_tool:*` records with enabled lifecycle, healthy status, low risk,
verified provenance, relative implementation paths, declared read-only
permissions, and matching descriptor hashes. Add table-driven snapshot
variants proving missing, extra, duplicate-issue, disabled, degraded,
non-low-risk, unverified, and digest-mismatched records are rejected while
unrelated Skill degradation is ignored.

- [x] **Step 2: Run capability tests and verify RED**

Run: `.\venv\Scripts\python.exe -m unittest tests.test_capability_registry tests.test_capability_resolver -v`

Expected: failures because `ROLE_TOOL` and `role_tool_assembly()` are absent.

- [x] **Step 3: Implement static discovery and assembly validation**

Add the enum member, call `_discover_role_tools()` from `_build_snapshot()`,
and map catalog entries to records only when the trusted implementation source
is a regular non-symlink file. Implement exact role-tool-only snapshot checks
before returning `RoleToolAssembly.for_catalog()`. Do not import the brain
implementation module or include handler data in any record.

- [x] **Step 4: Run capability suites GREEN**

Run: `.\venv\Scripts\python.exe -m unittest tests.test_capability_registry tests.test_capability_resolver -v`

Expected: all selected tests pass, including existing no-import and path-boundary tests.

### Task 3: Require evidence at the broker and Worker boundaries

**Files:**
- Modify: `src/core/brain/read_only_role_tools.py`
- Modify: `src/core/brain/role_worker.py`
- Modify: `tests/test_read_only_role_tools.py`
- Modify: `tests/test_role_worker.py`

**Interfaces:**
- Consumes: `RoleToolAssembly` and `role_tool_definitions()` from Task 1.
- Produces: `create_read_only_role_tool_broker(..., assembly: RoleToolAssembly)` and required trusted config key `role_tool_assembly`.

- [x] **Step 1: Add failing broker and child-runner tests**

Assert broker creation rejects missing or mismatched assembly before returning
any definitions, valid assembly preserves exact authorized tools, and
`execute_role_task()` rejects absent/invalid evidence before constructing
`AgentFactory`. Update the direct runner success test to assert the parsed
assembly is passed to the broker and no request field can alter it.

- [x] **Step 2: Run role-tool and Worker tests and verify RED**

Run: `.\venv\Scripts\python.exe -m unittest tests.test_read_only_role_tools tests.test_role_worker.TestRoleWorkerSupervisor -v`

Expected: focused failures because assembly is not required or forwarded.

- [x] **Step 3: Replace duplicate definitions and enforce assembly**

Remove the inline `_definitions()` table, import definitions from the catalog,
require a typed assembly parameter, and validate it against the static catalog
before constructing handlers. In `execute_role_task()`, parse
`trusted_config["role_tool_assembly"]` before manager, broker, or factory setup;
pass only the typed value to the broker.

- [x] **Step 4: Run broker and Worker suites GREEN**

Run: `.\venv\Scripts\python.exe -m unittest tests.test_read_only_role_tools tests.test_role_worker -v`

Expected: all selected tests pass with existing tool invocation, termination, usage, redaction, and audit behavior intact.

### Task 4: Wire service-owned registry evidence into default Workers

**Files:**
- Modify: `src/main.py`
- Modify: `src/main_fastapi.py`
- Modify: `tests/test_main.py`
- Modify: `tests/test_main_fastapi.py`

**Interfaces:**
- Consumes: `CapabilityRegistry.role_tool_assembly().to_dict()`.
- Produces: default `RoleWorkerSupervisor` runner config containing `role_tool_assembly`; injected supervisors keep identity and avoid unused assembly work.

- [x] **Step 1: Add failing AppState ownership tests**

Assert each default service constructor passes exactly the evidence returned by
its created or injected capability registry. Assert a provided role supervisor
does not call `role_tool_assembly()`, preserving existing dependency ownership
and tests that inject fake supervisors.

- [x] **Step 2: Run service lifecycle tests and verify RED**

Run: `.\venv\Scripts\python.exe -m unittest tests.test_main.TestMainHTTPStateLifecycle tests.test_main_fastapi.TestMainFastapiIntegration -v`

Expected: the default runner config lacks `role_tool_assembly`.

- [x] **Step 3: Reorder construction and pass serialized evidence**

Initialize the capability registry before the conditional default supervisor
in both AppState implementations. Only inside `if role_tasks is None`, call
`role_tool_assembly().to_dict()` and add it to trusted runner config. Preserve
resolver/target setup, injection identity, shutdown order, and all roots.

- [x] **Step 4: Run both service suites GREEN**

Run: `.\venv\Scripts\python.exe -m unittest tests.test_main tests.test_main_fastapi -v`

Expected: all selected HTTP, lifecycle, dispatch, and capability tests pass.

### Task 5: Extend the additive OpenAPI and frontend contract

**Files:**
- Modify: `contracts/core-api.openapi.json`
- Modify: `frontend/src/types/api.ts`
- Modify: `frontend/src/views/PluginsView.tsx`
- Modify: `frontend/src/tests/domain-views.test.tsx`
- Modify: `tests/test_api_contract.py`

**Interfaces:**
- Consumes: public kind string `role_tool` and unchanged `CapabilityRecord` shape.
- Produces: query enum, ID pattern, record enum, typed UI summary, `Wrench` icon, and read-only role-tool rendering.

- [x] **Step 1: Add failing contract and view tests**

Update the API contract expectation to include `role_tool`. Add a role-tool
fixture to the Plugins view test and assert the four-kind summary and record
label render while no lifecycle command is exposed for the capability record.

- [x] **Step 2: Run backend and frontend tests and verify RED**

Run:

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_api_contract -v
Set-Location frontend
npm test -- --run src/tests/domain-views.test.tsx
Set-Location ..
```

Expected: enum and UI count/label assertions fail because the public clients know only three kinds.

- [x] **Step 3: Implement the additive contract**

Add `role_tool` to both OpenAPI enums and the capability ID regex. Extend the
TypeScript union and count record. Render a Lucide `Wrench` icon, the label
`角色工具`, and a summary count. Keep capability records read-only and do not
add any action button or API method.

- [x] **Step 4: Run contract, frontend test, typecheck, and build GREEN**

Run:

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_api_contract -v
Set-Location frontend
npm test -- --run src/tests/domain-views.test.tsx
npm run typecheck
npm run build
Set-Location ..
```

Expected: all commands exit zero.

### Task 6: Self-review, full verification, and Iteration 148 evidence

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/DEVELOPMENT_GUIDE.md`
- Modify: `docs/reports/PROJECT_ANALYSIS.md`
- Modify: `docs/reports/README.md`
- Create: `docs/reports/AUDIT_REPORT_148.md`
- Delete: `docs/reports/AUDIT_REPORT_138.md`

**Interfaces:**
- Consumes: fresh validation output and the rolling ten-report policy.
- Produces: accurate Iteration 148 status, counts, architecture boundary, remaining priorities, and reproducible evidence.

- [x] **Step 1: Review the exact task diff locally**

Inspect only the Iteration 148 files in staged and unstaged views. Confirm one
catalog owns all definitions, records contain no executable objects, evidence
contains only IDs/digest/version, all failure cases close before model dispatch,
and no role grant or non-production broker behavior changed. Apply only
high-confidence fixes and rerun focused tests after any edit.

- [x] **Step 2: Run Python verification and record exact totals**

Run:

```powershell
.\venv\Scripts\python.exe tests/run_all.py
.\venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
.\venv\Scripts\python.exe -m compileall -q src tests scripts
.\venv\Scripts\python.exe -m ruff check src tests scripts
```

Expected: aggregate and discovery pass except the two established skips;
compileall exits zero; Ruff is compared against the known 152 findings.

- [x] **Step 3: Run frontend, browser, and integration gates**

Run:

```powershell
Set-Location frontend
npm test -- --run
$env:JARVIS_E2E_PORT = "5174"
npm run test:e2e
Remove-Item Env:JARVIS_E2E_PORT
npm run typecheck
npm run build
Set-Location ..
.\venv\Scripts\python.exe scripts\ci_local_integration.py --require-services
git diff --check
```

Expected: Vitest, Playwright with its documented desktop conditional skip,
typecheck, build, local integration, and whitespace validation pass.

- [x] **Step 4: Update the rolling evidence from fresh results**

Create `AUDIT_REPORT_148.md`, remove only `AUDIT_REPORT_138.md`, update the six
maintained navigation/status documents, and record exact current totals. State
that the five public records do not grant execution and that OS-level
filesystem/network isolation and non-role Broker expansion remain future work.

- [x] **Step 5: Perform final consistency checks**

Run:

```powershell
rg -n "TB[D]|TO[D]O|Iteration 147|138-147|22 条记录|22 records" README.md AGENTS.md CHANGELOG.md docs/DEVELOPMENT_GUIDE.md docs/reports/PROJECT_ANALYSIS.md docs/reports/README.md docs/reports/AUDIT_REPORT_148.md docs/superpowers/specs/2026-08-17-role-tool-capability-assembly-design.md docs/superpowers/plans/2026-08-17-role-tool-capability-assembly.md
git diff --check
git status --short
```

Expected: no stale current-state claims or placeholders in Iteration 148 scope,
no whitespace errors, and only intended mixed-worktree changes remain.
