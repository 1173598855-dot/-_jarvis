# AUDIT_REPORT_256.md

**Iteration**: #256
**Date**: 2026-09-30
**Status**: Complete

## Scope

This iteration delivers the final architectural Phase F work package: the
`MemoryRepository` port with its unified conformance contract. The port
freezes the bounded storage surface the app layer and role tools consume
(`read_only`, `memory_dir`, `load`, `store`, `get_stats`) so a future file,
SQLite or vector-backed implementation can be registered at the composition
root and verified by the same contract. The Markdown `MemoryStore` is the
reference implementation and the Markdown files remain the single
authoritative source; nothing about storage behavior changes in this
iteration.

## Changes

- Added `core/contracts/memory_repository.py` defining `MemoryRepository` as
  a structural `typing.Protocol` with port id/version constants. The
  structural form is deliberate: the hardened reference store predates the
  port and conforms without any change to its shape, and `isinstance`
  checks work at runtime.
- Added `check_memory_repository_conformance`, the unified extension
  contract test from the development guide: writable repositories verify the
  full store/load round trip, load determinism, statistics and the refusal
  of read-only budget kwargs; read-only repositories verify bounded loads,
  determinism, statistics and the write refusal against a *valid* entry, so
  a broken implementation cannot pass by raising for the wrong reason.
- Aligned the shared memory reader (`load_memory_entries_for_api`) with the
  port annotation; consumers keep their existing behavior.
- Added 6 focused tests: port metadata stability, writable and read-only
  `MemoryStore` conformance, writable budget refusal, and the checker's
  rejection of non-conforming objects and of a read-only fake that accepts
  writes.
- Archived `AUDIT_REPORT_246.md` per the ten-report window rule, registered
  in `manifest.json` with SHA-256 and size.

## Verification

| Command | Result |
|---|---|
| `python -m unittest tests.test_memory_repository -v` | 6 passed |
| `python tests/run_all.py` | Total: 1247; passed: 1236; skipped: 11 |
| `python -m unittest tests.test_api_contract` | 31 passed |
| `python -m compileall -q src tests scripts` | Passed |
| `python -m ruff check src tests scripts` | Passed |
| `git diff --check` | Passed |

Frontend sources are unchanged in this iteration; Vitest coverage from
Iteration 255 (158 tests) remains current.

## Residual Risk

- The port is structural, so a future implementation can satisfy
  `isinstance` with matching method names but diverging semantics; the
  conformance checker is the behavioral gate and must be run before any new
  repository is registered.
- The writable-mode rule that budget kwargs are refused is enforced as a
  behavioral check rather than by typing.
- Entry-level retention policies remain the last open Phase F work package.
