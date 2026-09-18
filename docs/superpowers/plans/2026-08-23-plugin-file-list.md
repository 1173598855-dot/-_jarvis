# Plugin `file.list` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a parent-owned, bounded, default-deny `file.list` Plugin Broker capability for deterministic direct-child discovery inside each plugin's validated root.

**Architecture:** Extend the existing rooted Broker dispatch table so `file.list` reuses the `file_read` Manifest permission and `bind_file_read_root()` fence while keeping an independent registration gate and stable denial reason. Scan direct children with one sentinel entry through `os.scandir()`, classify metadata without following links, and expose the result through `XiaoYiPluginAPI.list_dir()`.

**Tech Stack:** Python 3.11+, standard-library `os.scandir`, `pathlib`, `unittest`, existing Plugin Broker and Worker protocol.

## Global Constraints

- `file.list` reuses the exact Manifest permission string `file_read`.
- Results contain only direct children and use the exact keys `name` and `type`.
- Result types are exactly `file`, `directory`, `link`, or `other`.
- Results are sorted by entry name.
- The direct-entry budget is exactly 8,192 and the first excess entry fails closed.
- Existing first-party grants remain unchanged.
- No production behavior is written before its failing test is observed.

---

### Task 1: Broker Contract And Bounded Scan

**Files:**
- Modify: `tests/test_plugin_broker.py`
- Modify: `src/core/kernel/plugin_broker.py`

**Interfaces:**
- Consumes: `PluginBroker.begin_lifecycle()`, `PluginBroker.bind_file_read_root()`, and the existing rooted capability dispatch.
- Produces: `FILE_LIST_CAPABILITY`, `FILE_LIST_PERMISSION`, `FILE_LIST_DENIED_REASON`, `MAX_FILE_LIST_ENTRIES`, `PluginBroker.register_file_list_handler()`, and `_file_list_handler(root, arguments)`.

- [ ] **Step 1: Write failing identifier and authorization tests**

Add tests that access new names with `getattr()` so the test module still imports
before production constants exist. Assert `file.list`, `file_read`,
`file_list_denied`, `8_192`, and the four authorization/root gates.

- [ ] **Step 2: Run the broker tests and verify RED**

Run: `python -m unittest tests.test_plugin_broker.TestPluginBroker.test_read_only_capability_identifiers_are_stable tests.test_plugin_broker.TestPluginBrokerFileList.test_file_list_requires_declaration_grant_registration_and_bound_root`

Expected: FAIL because the identifiers and registration method do not exist.

- [ ] **Step 3: Implement identifiers and rooted registration**

Add the constants and `MANIFEST_PERMISSION_BY_CAPABILITY` entry, add the rooted
dispatch tuple `("_file_list_registered", "_file_list_handler", FILE_LIST_DENIED_REASON)`, initialize the registration flag, and add:

```python
def register_file_list_handler(self) -> None:
    with self._lock:
        self._file_list_registered = True
```

- [ ] **Step 4: Write failing scan behavior tests**

Cover sorted `name`/`type` snapshots, nested directories, traversal and component
links, exact-budget acceptance, sentinel overflow rejection, invalid argument
shapes, non-directory targets, and scan/metadata failures.

- [ ] **Step 5: Run the scan tests and verify RED**

Run: `python -m unittest tests.test_plugin_broker.TestPluginBrokerFileList`

Expected: FAIL because `_file_list_handler` is absent.

- [ ] **Step 6: Implement the minimal bounded handler**

Validate exactly `path`, resolve it under the bound root using the existing
component-link fence, require a directory, then use context-managed
`os.scandir()` to collect at most `MAX_FILE_LIST_ENTRIES` entries plus one
sentinel. Classify each entry with no-follow metadata and sort the returned
objects by `name`. Convert all filesystem and encoding failures into
`PluginCapabilityDenied(FILE_LIST_DENIED_REASON)`.

- [ ] **Step 7: Run broker tests and verify GREEN**

Run: `python -m unittest tests.test_plugin_broker`

Expected: all broker tests pass.

### Task 2: SDK And Worker Integration

**Files:**
- Modify: `tests/test_plugin_sdk_extended.py`
- Modify: `tests/test_plugin_sdk.py`
- Modify: `tests/test_subprocess_plugin_runtime.py`
- Modify: `src/core/kernel/plugin_api.py`
- Modify: `src/core/kernel/plugin_sdk.py`

**Interfaces:**
- Consumes: Broker capability `file.list` with arguments `{"path": str}`.
- Produces: `XiaoYiPluginAPI.list_dir(path: str = ".") -> Any` and default `PluginManager` handler registration.

- [ ] **Step 1: Write failing SDK and manager tests**

Assert `list_dir()` delegates to `file.list`, `PluginManager` registers the
handler, and default first-party grants still deny it.

- [ ] **Step 2: Run SDK tests and verify RED**

Run: `python -m unittest tests.test_plugin_sdk_extended.TestXiaoYiPluginAPI tests.test_plugin_sdk.TestPluginManagerBrokerRegistration`

Expected: FAIL because `list_dir()` and manager registration are absent.

- [ ] **Step 3: Implement SDK and manager wiring**

Add:

```python
def list_dir(self, path: str = ".") -> Any:
    return self._broker_request("list_dir", "file.list", {"path": path})
```

Register `file.list` in `PluginManager.__init__()` after `file.read`.

- [ ] **Step 4: Write and run failing Worker e2e tests**

Add one plugin that asserts the returned root snapshot and one ungranted plugin
that must fail activation with `PLUGIN_BROKER_DENIED`. Run the two new tests and
verify RED before implementation wiring, then rerun after Step 3 for GREEN.

- [ ] **Step 5: Run the plugin integration modules**

Run: `python -m unittest tests.test_plugin_broker tests.test_plugin_sdk tests.test_subprocess_plugin_runtime tests.test_plugin_worker_entrypoint tests.test_plugin_worker_protocol tests.test_plugin_sdk_extended tests.test_plugin_sdk_extended_v2 tests.test_plugin_installation`

Expected: all tests pass.

### Task 3: Aggregate Registration And Iteration Evidence

**Files:**
- Modify: `tests/run_all.py`
- Modify: `AGENTS.md`
- Modify: `CHANGELOG.md`
- Modify: `README.md`
- Modify: `docs/DEVELOPMENT_GUIDE.md`
- Modify: `docs/reports/PROJECT_ANALYSIS.md`
- Modify: `docs/reports/README.md`
- Create: `docs/reports/AUDIT_REPORT_224.md`
- Delete: `docs/reports/AUDIT_REPORT_214.md`

**Interfaces:**
- Consumes: verified test totals from the commands below.
- Produces: Iteration 224 ledger and a rolling report window of 215-224.

- [ ] **Step 1: Register the new broker test class in the aggregate suite**

Add `TestPluginBrokerFileList` to both the import and suite list in
`tests/run_all.py`.

- [ ] **Step 2: Run focused static checks**

Run: `python -m compileall -q src tests scripts`

Run: `python -m ruff check src tests scripts`

Expected: both commands exit zero.

- [ ] **Step 3: Run aggregate and full discovery tests**

Run: `python tests/run_all.py`

Run: `python -m unittest discover -s tests -p "test_*.py"`

Expected: both commands exit zero; record their exact totals.

- [ ] **Step 4: Update iteration documents with exact evidence**

Record the exact aggregate/discovery totals, capability contract, self-review,
changed files, and rolling report window. Remove only
`docs/reports/AUDIT_REPORT_214.md` after confirming report 224 exists.

- [ ] **Step 5: Run ledger and diff verification**

Run: `python -m unittest tests.test_iteration_ledger`

Run: `git diff --check`

Expected: both commands exit zero.

- [ ] **Step 6: Commit the implementation**

```powershell
git add src/core/kernel/plugin_broker.py src/core/kernel/plugin_api.py src/core/kernel/plugin_sdk.py tests/test_plugin_broker.py tests/test_plugin_sdk.py tests/test_plugin_sdk_extended.py tests/test_subprocess_plugin_runtime.py tests/run_all.py AGENTS.md CHANGELOG.md README.md docs/DEVELOPMENT_GUIDE.md docs/reports/PROJECT_ANALYSIS.md docs/reports/README.md docs/reports/AUDIT_REPORT_224.md docs/reports/AUDIT_REPORT_214.md docs/superpowers/specs/2026-08-23-plugin-file-list-design.md docs/superpowers/plans/2026-08-23-plugin-file-list.md
git commit -m "feat(plugin): bounded read-only file.list broker (Iteration 224)"
```
