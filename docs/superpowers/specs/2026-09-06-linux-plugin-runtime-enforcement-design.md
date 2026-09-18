# Linux Plugin Runtime Enforcement Design

## Context

Iteration 245 proves that the production network-namespace and
Landlock primitives enforce their intended boundary in a real Linux child.
Cross-platform runtime tests separately prove that `SubprocessPluginRuntime`
starts the Worker, attaches containment, completes its handshake, and applies
the child-side isolation calls before importing Plugin code. No test currently
combines those two claims on a real Linux kernel, so a future entrypoint or
environment regression could preserve both unit suites while weakening the
actual production launch chain.

## Goal

Add an opt-in Linux enforcement test that runs a real
`SubprocessPluginRuntime` as an unprivileged identity and proves that Plugin
code loaded through the production lifecycle cannot read or modify an outside
file or connect to a parent loopback listener, while it can still write within
the Worker-owned temporary root and emit its result through the existing
parent-owned Broker.

## Considered Approaches

1. **Production Runtime with a purpose-built Plugin (selected).** Exercise
   `start`, `load`, `activate`, Broker event commit, and `close` without adding
   a production test hook. This covers the complete launch and lifecycle path.
2. **A second primitive-only subprocess probe.** This would be simpler, but it
   would duplicate Iteration 245 and leave the production entrypoint gap.
3. **Add a diagnostic operation to the Worker protocol.** This would make the
   probe easy to drive but would expand a security-sensitive production
   contract solely for testing, so it is rejected.

## Design

The test module is gated by Linux plus
`JARVIS_RUN_LINUX_PLUGIN_RUNTIME_ENFORCEMENT=1`. Its unittest method launches a
small probe driver in a subprocess. When the test process is root, the driver
runs as UID/GID 12345; otherwise it retains the caller's non-root identity. The
driver first proves that its outside file and live loopback listener are
accessible before the Worker starts.

The driver creates a temporary Plugin whose `activate()` function attempts five
operations: outside read, outside write, a write to a DAC-writable marker in
the read-only Plugin root, loopback connection, and a write below
`tempfile.gettempdir()`. It sends the outcomes through the existing
`event.emit` capability. A normal `PluginBroker`, `EventBus`, `PluginLoadSpec`,
and `SubprocessPluginRuntime` then execute the real `LOAD` and `ACTIVATE`
lifecycle. The parent asserts the committed event payload, lifecycle success,
distinct Worker PID, confirmed shutdown, unchanged outside and Plugin-root
content, and the existence of the Worker-root probe before cleanup.

All lifecycle operations use fixed deadlines. The outer test drains stdout and
stderr concurrently with an 8 KiB limit per stream. On timeout, overflow or
another collection failure it reads the Worker PID sidecar plus the driver's
bounded `/proc` children snapshot, kills the independent Worker process groups
before the driver group, and requires bounded exit confirmation. The driver
closes the Runtime and EventBus from its widest ownership scope; the outer test
owns the listener and temporary tree. Ordinary aggregate/discovery runs and
non-Linux hosts skip the kernel probe honestly while the harness regressions
still run.

The existing Ubuntu 22.04 `linux-sandbox` CI job is extended to enable and run
this test beside the primitive enforcement probe. The test uses only standard
library and repository-owned components.

## Scope Boundaries

- Do not change Worker, Broker, Plugin, or lifecycle production contracts.
- Do not grant a new capability or expose an isolation bypass.
- Do not use a fake socket, fake filesystem denial, or injected isolation API.
- Do not claim Windows execution as Linux kernel evidence.
- Do not require root; root is used only to select a stable non-overflow test
  identity before the probe driver starts.

## Acceptance

- The real Plugin lifecycle reaches `loaded` and `enabled` through a distinct
  production Worker process.
- The driver baseline can read/write the outside file and Plugin-root marker,
  and can reach the listener.
- Plugin code is denied outside read/write, Plugin-root write and loopback
  access.
- Plugin code can write only in its Worker-owned temporary root and emit the
  exact bounded result through the Broker.
- Runtime shutdown is confirmed; timeout and overflow paths reclaim both
  independent process groups before owned filesystem cleanup.
- The focused WSL2 probe, Linux CI contract, aggregate suite, discovery, Ruff,
  compileall, and relevant frontend/documentation gates pass.
