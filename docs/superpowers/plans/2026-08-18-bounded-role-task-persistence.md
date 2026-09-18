# Bounded Role-Task Persistence Plan

## Scope

Harden `RoleTaskRecordRepository` recovery and snapshot writes without changing
the Worker protocol or public role-task API.

## Steps

- [x] Read the repository, Worker protocol, FastAPI lifecycle wiring, and
  existing persistence tests.
- [x] Add failing regressions for binary sentinel reads, oversized recovery,
  stat-underreported growth, and atomic oversized-save rejection.
- [x] Implement the shared 8 MiB bounded reader and iterated JSON encoder.
- [x] Run the role-task persistence suite, compile checks, Ruff, and diff checks.
- [x] Run aggregate and full Python validation, then record fresh evidence in
  the iteration ledger.

## Exit Criteria

The repository must preserve malformed-file fail-closed behavior and atomic
replacement while never opening a role-task snapshot above the configured byte
budget or replacing the prior snapshot with an oversized serialization.
