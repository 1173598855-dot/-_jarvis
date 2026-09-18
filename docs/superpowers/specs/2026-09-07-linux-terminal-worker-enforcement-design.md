# Linux Terminal Worker Enforcement Design

## Context

The Linux namespace and Landlock primitives have real Ubuntu 24.04 WSL2
evidence, and the production Plugin Runtime has a complete opt-in enforcement
probe. The fixed `TerminalWorker` still has only unit and ordinary integration
coverage. Its public protocol deliberately exposes five fixed read-only
operations and accepts no caller path, environment or network override, so none
of those operations can directly demonstrate a denied outside file or live
loopback connection.

## Goal

Exercise the real Linux `TerminalWorker` parent/child request chain and prove
that its child cannot read or modify an outside file, modify its readable source
tree, or connect to a live parent loopback listener, while its Worker-owned root
remains writable and is reclaimed after close.

## Considered Approaches

1. Reuse the Plugin Runtime probe. This proves the shared primitives but does
   not traverse `TerminalWorker.execute()`, its request protocol, containment or
   cleanup ownership.
2. Add an internal probe operation or caller-supplied targets to the production
   Terminal protocol. This would make the evidence direct, but it weakens the
   fixed-operation contract solely for tests.
3. Instrument only the opt-in test child command. Keep the production parent,
   protocol, `_worker_main()`, isolation calls and cleanup unchanged; replace
   the isolated operation body with a probe shim and mutation-check both kernel
   boundaries.

Approach 3 is selected. It provides production-chain evidence without adding a
production hook, dependency, command or environment variable.

## Architecture

The platform-gated test stages the repository `src/` tree with the existing
bounded, link-rejecting `stage_worker_tree()` primitive. It then starts an outer
driver as an unprivileged identity when the test host is root. The driver proves
that the outside file, staged-source marker and parent listener are accessible
before constructing the production `TerminalWorker` from the staged tree.

Inside the driver, a narrow `subprocess.Popen` wrapper accepts only the exact
production Terminal child command. It preserves the production cwd,
environment, pipes and process-group arguments, records the real child PID, and
substitutes a probe shim path. The shim imports the same staged production
module, replaces `_run_read_only_operation()` only, and calls the production
`_worker_main()`. Consequently resource limits, network isolation, filesystem
isolation, privilege handling, request parsing and response serialization run
in their production order. Probe targets travel only as shim arguments and do
not enter the production environment or request contract.

The isolated operation returns bounded JSON through the normal
`TerminalResult.stdout` field. The outer test requires:

- baseline outside read/write, source-marker write and loopback access;
- restricted outside read/write and source-marker write denial;
- restricted source-marker read and Worker-root write success;
- restricted parent loopback denial;
- a distinct real child PID, successful correlated Terminal response, confirmed
  child exit, Worker-root existence before close and reclamation after close.

## Mutation Evidence

The same probe runs twice more with test-only shim mutations. Disabling the
filesystem call must make outside and source-marker writes succeed while
network denial remains. Disabling the network call must make the parent
loopback connection succeed while Landlock denials remain. These runs prove
that the assertions detect missing enforcement rather than ordinary DAC,
listener or fixture behavior.

## Harness Boundaries

- Run only when Linux and
  `JARVIS_RUN_LINUX_TERMINAL_WORKER_ENFORCEMENT=1` are both present; ordinary
  aggregate and discovery runs report honest skips.
- Reuse the existing 8 KiB-per-stream collector and nested Worker-first process
  group terminator from the Plugin Runtime probe.
- Apply a 20-second driver deadline and fail if bounded cleanup cannot be
  confirmed after timeout, overflow or malformed output.
- Add the probe to the existing Ubuntu 22.04 `linux-sandbox` job and aggregate
  suite; do not claim Windows execution as Linux evidence.

## Scope Boundaries

- No production source, Terminal command, request field, environment whitelist,
  dependency or public API change.
- No direct-spawn fallback or isolation-disable behavior in production.
- The shim is test instrumentation, not executable application code.
- Existing Plugin and primitive evidence remains independent.

## Acceptance

- Aggregate and workflow guard tests fail before the probe is wired.
- All three opt-in probe runs pass on Ubuntu 24.04 WSL2 under a non-overflow
  unprivileged UID/GID.
- Normal Windows verification skips the three real tests explicitly.
- Terminal, isolation, aggregate wiring, CI workflow, Ruff, compileall,
  aggregate, discovery and frontend gates pass.

