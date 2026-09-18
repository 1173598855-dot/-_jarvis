# Bounded Capability Registry collections Implementation Plan

> **For agentic workers:** Execute with the project's existing TDD and review
> workflow. Keep unrelated mixed-worktree changes intact.

**Goal:** Bound directory and tree-file candidate retention without changing
Capability Registry records or error contracts.

**Architecture:** Add one module-local heap-based bounded selection helper and
reuse it for direct children and tree files.

## Tasks

- [x] Add a regression proving bounded selection keeps only a fixed candidate
  window while preserving count and deterministic minimum values.
- [x] Route `_children()` through the collector and retain its existing
  `*_child_limit` issue behavior.
- [x] Route `_hash_tree()` through the collector and preserve symlink and
  `tree_file_limit` error precedence.
- [x] Complete self-review and full project verification.
- [x] Update Iteration 185 ledger and rolling audit report.
