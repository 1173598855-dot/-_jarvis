# Fixed Terminal Worker OS Isolation Design

## Goal

Give the fixed, read-only `TerminalWorker` a parent-owned OS boundary on
Windows and macOS while preserving the existing Linux child-applied boundary,
wire protocol, audit behavior, and cleanup guarantees.

## Decision

Reuse the existing `WindowsWorkerContainer`, `MacOSSandbox`, and shared
`stage_worker_tree()` primitives instead of introducing a second sandbox
implementation. Each `TerminalWorker` lazily owns one platform sandbox
generation for its lifetime. The trusted `src/` tree is staged once into the
generation's read-only code area; every short-lived command Worker runs from
that staged tree and uses the generation's single writable root for its
temporary directory.

Automatic selection is enabled only for an unpatched real `subprocess.Popen`
on Windows or macOS. Linux keeps the current direct launch plus child-applied
network namespace and Landlock setup. `os_isolation=False` remains an explicit
compatibility/test escape hatch; injected platform factories remain test seams.
When isolation is selected, sandbox creation, staging, launch, containment,
or Windows resume failure returns the existing terminal failure result and
never falls back to direct spawning.

## Boundaries and lifecycle

The parent retains the real source tree and the existing public
`TerminalWorker.sandbox_dir` compatibility directory. On an isolated launch,
the child receives only the platform sandbox writable root in `TMP`/`TEMP` or
`TMPDIR`, and `PYTHONPATH` points at the staged source tree. The child is
started as:

```text
<interpreter> -S -u -m core.kernel.terminal_worker --worker
```

with the staged source directory as its working directory. Windows uses the
container's verified base interpreter; macOS uses the current interpreter,
whose runtime paths are already included in the Seatbelt profile.

`-S` disables ambient site-package startup while still allowing the explicit
staged `PYTHONPATH` to expose the Worker module. `-I` was rejected during the
Windows runtime probe because isolated mode removed the staged import path.

The parent-owned sequence is:

```text
create sandbox → stage trusted src tree → spawn child →
attach ProcessTreeContainment → resume suspended Windows child →
exchange bounded request/response → terminate/reap →
release containment → close platform sandbox
```

The platform sandbox is retained while a containment cannot yet be released.
`TerminalWorker.close()` retries containment and sandbox cleanup on later calls,
and does not mark the instance closed until all owned resources are released.

## API changes

`TerminalWorker.__init__` gains optional keyword-only controls:

- `os_isolation: bool | None = None`: explicit selection override;
- `container_factory`: injected `WindowsWorkerContainer` factory;
- `macos_sandbox_factory`: injected `MacOSSandbox` factory.

The Worker-side `TerminalExecutor` accepts the platform sandbox's existing
writable root through its external `sandbox_dir` option. It never creates or
deletes a nested temporary directory, so the platform policy and cleanup owner
remain singular.

The default remains automatic platform selection. No terminal request fields,
command allowlist, response schema, timeout, or audit record fields change.

## Error handling

- Unsupported explicit isolation fails closed with a terminal failure result.
- Missing launcher, AppContainer setup, staging overflow/link, invalid staged
  paths, spawn failure, containment failure, or resume failure fail closed.
- A failed isolated setup is cleaned up best-effort and never retries through
  ordinary `subprocess.Popen`.
- Existing timeout, bounded stdout/stderr, process-tree termination, response
  validation, and parent sandbox cleanup semantics remain unchanged.

## Verification

Contract tests will cover automatic selection, explicit override precedence,
Windows and macOS argument/environment/cwd wiring, staging reuse, containment
before Windows resume, setup failure cleanup, no direct-spawn fallback, and
retry-safe cleanup. Existing terminal Worker regressions, aggregate Python
tests, full discovery, Ruff, compile checks, and frontend checks remain the
release gates. This Windows host can verify policy and lifecycle logic only;
actual macOS Seatbelt enforcement still requires a macOS host or CI runner.
