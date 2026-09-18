# Linux Worker Enforcement Design

## Context

The Linux Plugin and Terminal Workers apply a network namespace followed by a
Landlock filesystem ruleset before loading plugin code or reading a terminal
request. Existing tests inject fake kernel interfaces, so they prove ordering
and fail-closed decisions but not kernel enforcement. A real Ubuntu 24.04 WSL2
probe exposed two production gaps:

- Landlock reports ABI 7, while `_handled_access_for_abi()` rejects every ABI
  above 3 even though newer ABIs remain compatible with older access masks.
- An unprivileged service user receives `EPERM` from `unshare(CLONE_NEWNET)`;
  creating a user and network namespace together is available and can provide
  the namespace capability without granting host privileges.

## Goal

Make the existing Linux Worker isolation path usable by an unprivileged user on
modern kernels and add a real enforcement probe that proves an outside file is
unreadable and unwritable, a Worker-owned root remains writable, and a live
parent loopback listener is unreachable.

## Design

`isolate_worker_network()` first keeps the current direct
`unshare(CLONE_NEWNET)` path. This preserves deployments that already grant the
required capability and avoids changing root behavior. Only an `EPERM` result
triggers one fallback: atomically create `CLONE_NEWUSER | CLONE_NEWNET`, then
write fixed current-UID/current-GID mappings to `/proc/self/uid_map` and
`/proc/self/gid_map`, with `/proc/self/setgroups` set to `deny` first. Any
fallback syscall, mapping, short-write, or close failure raises
`WorkerNetworkIsolationError`; other direct errors never fall back.

`_handled_access_for_abi()` treats ABI 3 as the highest userspace ABI this
implementation understands. Kernels reporting ABI 3 or newer receive the ABI 3
handled-access mask, while ABI 1 and 2 retain their existing masks. The returned
isolation evidence continues to record the actual kernel ABI.

The real Linux test runs only when both `sys.platform` is Linux and
`JARVIS_RUN_LINUX_ISOLATION_ENFORCEMENT=1`. It starts a child as an
unprivileged identity when the test process is root, keeps a real parent
loopback listener open, applies network then filesystem isolation in the child,
and asserts exact JSON outcomes. Normal cross-platform discovery records an
explicit skip; a dedicated Ubuntu CI job enables the probe.

## Scope Boundaries

- Do not change Plugin/Terminal Worker protocols, grants, Broker behavior, or
  Windows/macOS launchers.
- Do not add a fallback that runs without either network or filesystem
  isolation.
- Do not claim local Windows evidence as Linux enforcement evidence.
- Do not add dependencies or support Landlock rights newer than ABI 3 until the
  implementation explicitly models those rights.

## Verification

- Unit tests must first fail for EPERM fallback and Landlock ABI 7, then pass.
- The real WSL2 probe must run under an unprivileged child and report four exact
  outcomes: outside read denied, outside write denied, loopback denied, Worker
  root write allowed.
- Worker integration tests, CI workflow contracts, Ruff, compileall, aggregate
  tests, and bounded full discovery must pass.

