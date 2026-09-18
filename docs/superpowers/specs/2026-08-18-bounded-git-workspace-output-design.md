# Bounded GitWorkspace Child-Process Output Design

## Context

`GitWorkspaceInspector._run()` used `subprocess.run(capture_output=True)` for
`rev-parse`, branch and porcelain status commands. A repository with a very
large status result could therefore retain unbounded stdout/stderr before the
workspace snapshot parser applied its existing path normalization.

## Decision

Use a process-owned concurrent reader for both pipes. Each stream retains at
most `_MAX_GIT_OUTPUT_BYTES = 8 * 1024 * 1024`; the first chunk beyond the
budget is truncated to the boundary, signals overflow and kills the child.
The reader loop keeps the existing 10-second deadline and sanitized environment.
Overflow raises `ValueError`, timeout raises `subprocess.TimeoutExpired`, and a
non-zero exit raises `subprocess.CalledProcessError` with bounded output.

## Compatibility

Successful Git commands still return bytes to the existing ASCII/UTF-8 parsers.
The command list, `shell=False`, repository cwd, environment allowlist and
porcelain parsing are unchanged. Both stdout and stderr are bounded even though
only stdout participates in the normal snapshot.

## Testing

Regression coverage proves the first overflow is rejected before porcelain
parsing, fixed commands retain their exact order and environment, and a real
temporary Git repository still produces the same snapshot.
