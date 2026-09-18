# macOS Plugin Worker Sandbox Design

## Goal

Give macOS Plugin Workers a parent-owned filesystem and network boundary that
matches the existing Worker lifecycle contract without claiming modern App
Sandbox entitlement support. The boundary must stage trusted Worker and Plugin
trees, expose one Worker-owned writable directory, deny network access by
default, and fail closed when the host lacks the required launcher or policy
support.

## Decision

Use the macOS `sandbox-exec` launcher with an inline Seatbelt profile. The
parent creates a private staging root, copies only bounded link-free trees, and
passes the generated profile plus the staged Worker entrypoint to
`sandbox-exec`. The profile grants read access only to the staged code,
staged Plugin, and the base Python runtime paths; it grants read/write access
only to the Worker temporary root. No network rule is added. The existing
`ProcessTreeContainment` attaches to the launched process and the existing
Broker continues to use the validated real Plugin root in the parent.

`sandbox-exec` is deprecated and may be unavailable or restricted on future
macOS versions. Its absence, policy construction failure, staging failure, or
launch failure is a stable `PLUGIN_WORKER_START_FAILED`; there is no ordinary
spawn fallback on macOS when automatic isolation is selected. Explicit
`os_isolation=False` remains a test/compatibility escape hatch, consistent with
the Windows integration.

## Boundaries

- The sandbox profile starts with `(deny default)`.
- Network access remains denied because no `network-*` allowance is emitted.
- Staged Worker and Plugin trees are bounded to the shared 8,192-entry budget
  and reject links before copying.
- The only write allowance is the exact Worker-owned temporary root.
- Runtime read paths are normalized, absolute, deduplicated and included in the
  profile; empty or invalid paths fail closed.
- Profile paths are escaped as Seatbelt string literals, never interpolated as
  shell syntax.
- The parent owns staging cleanup and keeps it until process exit, readers,
  and process-tree containment are confirmed.
- The current Windows host can verify policy construction and fail-closed
  decision logic only. Real kernel enforcement requires a macOS runner and is
  not represented as a passing local test.

## Interfaces

`MacOSSandbox.create()` returns one parent-owned sandbox generation with:

- `stage(source, name) -> Path`
- `spawn(arguments, cwd, environment, ...) -> Popen-compatible process`
- `close()`

`SubprocessPluginRuntime` selects this generation automatically for a real
macOS `subprocess.Popen`, while injected factories make the branch testable on
other hosts. Windows continues using `WindowsWorkerContainer`; POSIX Linux
continues using its existing child-applied namespace/Landlock path.

## Verification

Contract tests cover profile contents, path escaping, link and entry budgets,
missing launcher failure, staging cleanup, runtime selection and no-fallback
behavior. Existing aggregate/discovery, Ruff, compile, frontend and diff
checks remain required. A macOS CI job or macOS host is required before making
any claim about kernel-enforced denial.

