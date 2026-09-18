# Plugin Worker Process-Tree Containment Design

**Date:** 2026-08-17
**Iteration:** 180

## Problem

`SubprocessPluginRuntime` owns and confirms only the direct Worker process.
Plugin lifecycle code can start descendants, so a successful direct-process
reap does not prove that the Worker generation stopped. Those descendants can
outlive cleanup and keep using inherited service-user authority.

## Required Behavior

- Every real Plugin Worker starts inside a parent-owned process-tree boundary.
- POSIX workers start a new session and are terminated through their process
  group.
- Windows workers are assigned to a Job Object configured with
  `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`; terminating or closing the Job owns all
  descendants in that generation.
- Boundary creation or attachment failure rejects Worker startup and reaps the
  direct process. A generation is never silently downgraded to direct-process
  ownership.
- Confirmed process exit closes the boundary only after reader threads stop.
  Unconfirmed exit retains the process, boundary, readers, and temporary
  directory for a later `close()` retry.
- Plugin protocol, Broker grants, lifecycle statuses, environment filtering,
  working-directory behavior, and public HTTP shapes remain unchanged.

## Architecture

Add `core.kernel.process_containment`, a small standard-library adapter with:

- `process_group_popen_kwargs()` for platform launch flags;
- `ProcessTreeContainment.attach(process)` to capture a POSIX process group or
  assign a real Windows `subprocess.Popen` to a kill-on-close Job Object;
- `terminate(force=...)` to signal the owned tree; and
- `close()` to release the platform handle after confirmed cleanup.

`SubprocessPluginRuntime.start()` creates and attaches the boundary before it
starts reader threads or accepts a handshake. `_terminate_process()` uses the
boundary for graceful and forced escalation, then closes it only when the
direct process and both reader threads are confirmed stopped.

Test doubles that are not real `subprocess.Popen` instances retain the current
direct-process fallback so existing protocol tests can model failures without
constructing OS handles. Production `Popen` instances must attach successfully.

## Error Handling

- Platform API setup or assignment errors become the existing bounded
  `PLUGIN_WORKER_START_FAILED` result.
- Tree termination failure keeps `termination_confirmed=False` and preserves
  all parent-owned resources for retry.
- Missing process groups and already-empty Job Objects are treated as cleaned;
  malformed or reusable caller PIDs are never accepted as input because the
  boundary is created only from the just-spawned `Popen` instance.

## Verification

- Unit tests cover POSIX launch/session and group signal behavior.
- Windows tests cover Job setup, assignment, termination, and handle close via
  injected kernel calls, plus one real Plugin Worker lifecycle on the current
  platform.
- Runtime regressions verify launch flags, startup failure containment,
  retained ownership on unconfirmed cleanup, and ordinary lifecycle behavior.
- Run Plugin suites, aggregate/discovery, static checks, frontend gates, and
  required-services integration.

## Scope Boundary

This iteration does not claim filesystem or network isolation, add resource
limits, allow new Plugin capabilities, or alter TerminalWorker. The fixed
TerminalWorker operations do not spawn external commands and retain their
existing short-lived process boundary.
