# Role Registry Deep Inheritance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve arbitrarily deep acyclic RoleRegistry inheritance chains
without Python recursion failures.

**Architecture:** Keep `register()` and cycle policy unchanged. Replace only
the recursive read helper with explicit chain collection and reverse folding,
using the existing merge constructor and ownership copies.

**Tech Stack:** Python standard library, `dataclasses`, `unittest`.

## Global Constraints

- Preserve missing-parent fallback and all Iteration 178 cycle semantics.
- Do not stage, commit, reset, clean, or overwrite unrelated worktree changes.
- Add the regression to `tests/run_all.py` through its existing test class.

---

### Task 1: Deep-chain Regression

**Files:**
- Modify: `tests/test_role_registry_extended_v2.py`
- Modify: `tests/run_all.py`

- [ ] **Step 1: Add a 1100-role chain test**

  Register `role-0` through `role-1099`, with each role pointing to the
  previous one and unique endpoint capabilities. Assert `get("role-1099")`
  succeeds, includes `cap-0` and `cap-1099`, and retains the deepest priority.

- [ ] **Step 2: Run the regression and verify RED**

  Run:
  `python -m unittest tests.test_role_registry_extended_v2.TestRoleRegistryDeepInheritance -v`

  Expected: FAIL with `RecursionError` against the recursive resolver.

### Task 2: Iterative Resolver

**Files:**
- Modify: `src/core/brain/role_registry.py`

- [ ] **Step 1: Collect the parent chain iteratively**

  Append the current profile while its parent exists. Stop at a root or missing
  parent and copy the deepest collected profile as the base.

- [ ] **Step 2: Fold the chain in reverse**

  Reuse the current `AgentProfile` merge fields and order while walking back to
  the original child, setting `parent_role=None` on each resolved child.

- [ ] **Step 3: Run affected tests and verify GREEN**

  Run the new test, all three RoleRegistry files, and targeted Ruff. Expected:
  zero failures and unchanged shallow/missing-parent behavior.

### Task 3: Delivery Evidence

**Files:**
- Modify: `AGENTS.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/reports/PROJECT_ANALYSIS.md`
- Modify: `docs/reports/README.md`
- Create: `docs/reports/AUDIT_REPORT_179.md`
- Delete: `docs/reports/AUDIT_REPORT_169.md`

- [ ] **Step 1: Run aggregate, discovery, frontend, integration, static, and
  ledger checks.**
- [ ] **Step 2: Self-review merge order, fallback ownership, depth behavior,
  and aggregate registration.**
- [ ] **Step 3: Record fresh counts and roll the report window to 170-179.**
