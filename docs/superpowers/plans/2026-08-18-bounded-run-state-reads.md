# Bounded Run State reads Implementation Plan

**Goal:** Bound every FileRunStateRepository recovery read before allocation.

- [x] Add RED tests for one-shot binary reads, stat-underreported growth, exact
  file limit acceptance, and aggregate snapshot overflow.
- [x] Route active manifest, revision, archive, verification, and atomic
  read-back paths through one bounded helper.
- [x] Preserve existing integrity error messages and stable state behavior.
- [x] Run persistence impact, aggregate/discovery, lint, frontend, and service
  gates.
- [x] Update Iteration 187 ledger and rolling audit report.
