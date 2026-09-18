# Role Registry Inheritance Cycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent RoleRegistry registrations from creating inheritance cycles
that later crash reads with `RecursionError`.

**Architecture:** Preserve `register()` as the only mutation boundary. Validate
the candidate's registered parent chain iteratively under the same lock as the
duplicate check and insertion, while continuing to accept missing parents as
forward references.

**Tech Stack:** Python standard library, `dataclasses`, `threading`, `unittest`.

## Global Constraints

- Do not stage, commit, reset, clean, or overwrite unrelated worktree changes.
- Preserve missing-parent fallback, duplicate error precedence, and snapshot
  ownership from Iteration 177.
- Add every regression to the canonical `tests/run_all.py` aggregate suite.

---

### Task 1: Cycle Regressions

**Files:**
- Modify: `tests/test_role_registry_extended_v2.py`
- Modify: `tests/run_all.py`

**Interfaces:**
- Consumes: `RoleRegistry.register(profile: AgentProfile) -> None`
- Produces: `TestRoleRegistryInheritanceCycles`, registered in the aggregate
  suite.

- [ ] **Step 1: Add direct and indirect cycle tests**

  Add a dedicated test class. Assert a self-parent registration raises
  `ValueError`; then register `child -> future_parent`, reject
  `future_parent -> child`, and assert `child` remains present while
  `future_parent` is absent.

- [ ] **Step 2: Run the tests and verify RED**

  Run:
  `python -m unittest tests.test_role_registry_extended_v2.TestRoleRegistryInheritanceCycles -v`

  Expected: both tests fail because current registration accepts the cycle.

### Task 2: Atomic Registration Validation

**Files:**
- Modify: `src/core/brain/role_registry.py`

**Interfaces:**
- Consumes: candidate `AgentProfile` and the lock-protected `_roles` mapping.
- Produces: `_validate_acyclic_registration(profile: AgentProfile) -> None`,
  raising deterministic `ValueError` before insertion.

- [ ] **Step 1: Implement the minimal iterative validator**

  Start with `path = [profile.name]` and `seen = {profile.name}`. Follow
  `profile.parent_role` and existing parent links. When a name is already in
  `seen`, append it and raise `ValueError` with the closed path; stop when the
  parent is missing or has no parent.

- [ ] **Step 2: Call the validator atomically**

  Invoke it inside `register()` after the existing duplicate-name check and
  immediately before assigning `_roles[profile.name]`.

- [ ] **Step 3: Run affected tests and verify GREEN**

  Run the new class, all role-registry suites, and the aggregate coverage
  guards. Expected: zero failures and no warnings.

### Task 3: Delivery Evidence

**Files:**
- Modify: `AGENTS.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/reports/PROJECT_ANALYSIS.md`
- Modify: `docs/reports/README.md`
- Create: `docs/reports/AUDIT_REPORT_178.md`
- Delete: `docs/reports/AUDIT_REPORT_168.md`

- [ ] **Step 1: Run project verification**

  Run the canonical aggregate suite, full discovery, Ruff, compileall,
  iteration-ledger tests, and `git diff --check`. Run frontend and local
  integration gates if the Python change or ledger verification requires a
  refreshed whole-project baseline.

- [ ] **Step 2: Self-review the diff**

  Check invariant preservation, error precedence, forward references,
  concurrency, aggregate registration, and that only Iteration 178 files are
  included in this cycle.

- [ ] **Step 3: Update ledgers and report window**

  Record fresh counts, add Iteration 178, and roll the ten-report window from
  `168-177` to `169-178` only after all required gates pass.
