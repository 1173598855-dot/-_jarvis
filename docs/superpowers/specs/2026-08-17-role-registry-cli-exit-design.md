# Role Registry CLI Exit Design

**Date:** 2026-08-17
**Iteration:** 176

## Problem

The `get` and `register` branches in `role_registry.py` call `sys.exit(1)`
after their missing-argument checks instead of inside them. Both documented
subcommands therefore terminate before processing valid arguments.

## Required Behavior

- `get <role_name>` prints the resolved role as JSON and exits with code 0.
- `register <json_file>` loads one profile, registers it in the process-local
  registry, prints the registered name, and exits with code 0.
- Missing arguments, unknown commands, and unknown roles retain their current
  failure behavior.
- Registry storage, inheritance, serialization, and service APIs remain
  unchanged.

## Design

Keep the existing dependency-free CLI and move each unconditional failure exit
into its corresponding missing-argument branch. Verify the public command-line
surface through real Python subprocesses so an early `SystemExit` cannot be
hidden by direct function mocks.

## Verification

- Add separate `get` and `register` subprocess regressions to the registered
  aggregate suite.
- Observe both regressions fail against the current implementation (RED).
- Apply the indentation-only control-flow fix and rerun the focused role
  registry suites (GREEN).
- Run warning, aggregate, discovery, frontend, integration, compile, lint, and
  repository consistency gates.

## Scope Boundary

This iteration does not replace the CLI parser, add persistence, change role
validation, or alter role inheritance semantics.
