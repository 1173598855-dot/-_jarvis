# Windows Plugin Worker AppContainer Integration Design

## Problem

Iteration 239 delivered a parent-owned Windows AppContainer identity and proved
filesystem and network denial against a real child, but the production
`SubprocessPluginRuntime` still needed a complete launch path. A Worker that
continues to start through ordinary `subprocess.Popen` does not receive the
boundary that the audit report claims. The integration must also preserve the
existing Broker, protocol, process-tree ownership and cleanup contracts.

The current working tree contains an in-progress implementation of this
integration. This design records the intended contract and the remaining
completion work without rewriting unrelated Iteration 225-239 changes.

## Approaches considered

1. Use a parent-owned `CreateProcessW` wrapper that carries
   `PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES`, stages trusted source and
   plugin trees into a private read-only area, and exposes one writable Worker
   root. This is selected because AppContainer identity must be present at
   process creation and the existing Python transport can continue to consume
   standard pipes.
2. Spawn a normal Python child and ask it to enter an AppContainer after start.
   This cannot work for the required boundary: Windows AppContainer identity is
   a process-creation attribute, and code can execute before the child applies
   any self-restriction.
3. Wrap the Worker in a shell or another helper process. This adds an
   unbounded executable and handle surface, does not itself provide the needed
   AppContainer security capability, and complicates process-tree ownership.

## Design

`worker_windows_isolation.py` owns profile creation/adoption, SID conversion,
ACL grants, interpreter readability checks and failure cleanup. Created profiles
are deleted on close; adopted profiles are never deleted by the caller. SID and
profile cleanup also runs when SID conversion or grants fail before an identity
object exists.

`worker_windows_container.py` owns one container generation. It creates a
temporary `code` directory and a single writable `tmp` directory, rejects
links and entry-count overflow before copying trusted `src` and plugin trees,
grants only the staged code read/execute access and the temporary root
read/write access, and starts the base interpreter with a capability-free
AppContainer token. `AppContainerPopen` uses a suspended `CreateProcessW`
launch with an explicit standard-handle list.

`SubprocessPluginRuntime` selects the container by default only for the real
Windows `subprocess.Popen`; an injected container factory may exercise the
branch on other hosts, while explicit `os_isolation=False` retains the direct
transport for test doubles and compatibility. After a contained process is
created, the runtime attaches `ProcessTreeContainment` before resuming the
suspended primary thread. No container setup failure may fall back to direct
execution. The Broker remains parent-owned and continues to bind the validated
real plugin root; the child receives only its staged plugin root.

## Error handling and cleanup

All profile, SID, ACL, staging, attribute-list, pipe and process-creation
failures fail closed as `PLUGIN_WORKER_START_FAILED` or the existing stable
transport error. A created but unusable container is closed before the start
error escapes. If a process exists, termination and process-tree confirmation
complete before the container stage and identity are released. A suspended
thread handle is closed on both resume success and every failure path.

## Testing

- Contract tests cover profile adoption/deletion, SID/grant failure cleanup,
  link and entry budgets, required environment, staged-tree cleanup and
  handle/identity launch attributes.
- Runtime tests cover default Windows selection, explicit bypass, injected
  container selection and cleanup after confirmed shutdown.
- The Windows-only real-enforcement test proves denied outside reads and
  loopback connections while the granted root remains writable, and its
  mutation check proves the denial comes from the AppContainer attribute.
- Existing aggregate/discovery, Ruff, compile, frontend and integration gates
  remain required; non-Windows runs report real-enforcement skips honestly.

## Acceptance criteria

- Every real Windows `SubprocessPluginRuntime` Worker starts through the
  parent-owned AppContainer path and never silently falls back to direct spawn.
- The SID-conversion failure path releases the returned SID and deletes a
  profile created by that attempt.
- Existing direct/POSIX runtime behavior and public Broker/protocol contracts
  remain unchanged.
- Focused tests, the aggregate suite, full discovery, Ruff, compile, frontend
  checks and diff integrity pass with updated Iteration 240 evidence.

