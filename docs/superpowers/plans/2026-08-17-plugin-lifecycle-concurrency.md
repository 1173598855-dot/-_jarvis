# Plugin Lifecycle Concurrency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Plugin Worker generation ownership and lifecycle transitions linearizable across concurrent service requests.

**Architecture:** Add one loader-owned `threading.RLock` and acquire it at every public manifest, registry, and lifecycle boundary. Keep the lock through bounded Worker I/O so partial generations cannot be observed or overwritten.

**Tech Stack:** Python 3.10+, `threading.RLock`, `unittest`, existing Plugin Worker coordinator fixtures.

## Global Constraints

- Preserve current HTTP, Manifest, Worker protocol, Broker, status, and error contracts.
- Preserve deterministic Plugin-ID close order and unconfirmed-worker retention.
- Do not introduce per-Plugin lock registries, transient statuses, dependencies, or unrelated refactors.

---

### Task 1: Prove concurrent exact loads leak Worker ownership

**Files:**
- Modify: `tests/test_plugin_sdk.py`

**Interfaces:**
- Consumes: `PluginLoader.load_plugin(manifest) -> PluginInstance`
- Produces: one deterministic concurrent-load regression in `TestPluginWorkerCoordinator`

- [ ] **Step 1: Add a gated runtime regression**

Create a `GatedStartRuntime` subclass whose first `start()` signals an entered
event and waits on a release event. Start two loader threads with the same
Manifest and assert only one runtime is created while the first is gated.

- [ ] **Step 2: Run the regression and verify RED**

Run: `python -m unittest tests.test_plugin_sdk.TestPluginWorkerCoordinator.test_concurrent_exact_loads_own_one_worker_generation -v`

Expected: FAIL because the second caller creates another runtime before the
first load publishes `_plugins[plugin_id]`.

### Task 2: Serialize PluginLoader public state boundaries

**Files:**
- Modify: `src/core/kernel/plugin_sdk.py`
- Test: `tests/test_plugin_sdk.py`

**Interfaces:**
- Consumes: existing `PluginLoader` public methods and internal lifecycle helpers
- Produces: loader-owned `_lifecycle_lock: threading.RLock`

- [ ] **Step 1: Add the minimal synchronization implementation**

Add a private decorator that acquires `self._lifecycle_lock`, initialize the
lock before shared loader state, and apply it to discovery, load, enable,
disable, unload, close, and registry read methods. Use `RLock` because close
calls unload while retaining the same lifecycle boundary.

- [ ] **Step 2: Run the regression and verify GREEN**

Run: `python -m unittest tests.test_plugin_sdk.TestPluginWorkerCoordinator.test_concurrent_exact_loads_own_one_worker_generation -v`

Expected: PASS; both callers return one `PluginInstance`, only one runtime and
generation exist, and no thread remains alive.

- [ ] **Step 3: Run affected Plugin suites**

Run: `python -m unittest tests.test_plugin_sdk tests.test_plugin_installation tests.test_subprocess_plugin_runtime tests.test_process_containment -q`

Expected: PASS with no failure, error, or resource warning.

### Task 3: Deliver Iteration 181 evidence

**Files:**
- Modify: `tests/run_all.py`
- Modify: `AGENTS.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/reports/PROJECT_ANALYSIS.md`
- Modify: `docs/reports/README.md`
- Create: `docs/reports/AUDIT_REPORT_181.md`
- Delete: `docs/reports/AUDIT_REPORT_171.md`

**Interfaces:**
- Consumes: final aggregate/discovery counts and verification output
- Produces: a ten-report rolling window for Iterations 172-181

- [ ] **Step 1: Register the concurrency regression in the aggregate suite**

Add its containing test class once if the class is not already aggregated;
otherwise the existing class registration must pick it up automatically.

- [ ] **Step 2: Run complete verification**

Run aggregate, discovery, compileall, Ruff, frontend Vitest/Playwright,
typecheck, build, required-services integration, and `git diff --check`.

- [ ] **Step 3: Update current evidence**

Record only the newly observed counts and results, roll the audit window by one
report, and state that lifecycle serialization does not provide OS resource
isolation.
