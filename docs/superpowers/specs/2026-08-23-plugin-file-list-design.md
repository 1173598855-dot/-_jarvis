# Bounded Plugin `file.list` Design

## Context

Iterations 219-223 added parent-owned, default-deny read-only Plugin Broker
capabilities. Plugins can read a known file through `file.read`, but they cannot
discover which files and directories exist under their validated plugin root.
The next increment adds bounded directory discovery without granting writes,
arbitrary host filesystem access, or a new Manifest permission family.

## Contract

- Capability identifier: `file.list`.
- Manifest permission: reuse `file_read` because listing and reading share the
  same plugin-root filesystem trust boundary.
- Stable policy denial: `file_list_denied`.
- Public SDK method: `XiaoYiPluginAPI.list_dir(path=".")`.
- Arguments: an object containing exactly one non-empty string field, `path`.
- Result: a deterministically sorted list of objects shaped as
  `{"name": <string>, "type": "file"|"directory"|"link"|"other"}`.
- Entry budget: at most 8,192 direct children. The first sentinel entry over
  the budget rejects the entire call before returning a partial snapshot.

## Authorization And Registration

`file.list` follows the existing Broker chain: the plugin must declare
`file_read`, the service must grant `file.list`, the parent must register the
handler, and the plugin must have a validated root bound through
`bind_file_read_root()`. `PluginManager` registers the handler by default, as it
already does for `file.read` and `config.get`, but the first-party grant table
remains unchanged and grants only `event.emit`.

## Path And Scan Boundary

The handler accepts only relative paths. Every requested path component is
checked for symlink or Windows reparse-point traversal before strict resolution,
and the resolved directory must remain inside the bound plugin root. The target
must be a directory.

The parent scans with context-managed `os.scandir()`. It collects no more than
8,192 entries and reads one sentinel entry to detect overflow. Entry metadata is
queried without following links. Any path-resolution failure, scan failure,
metadata failure, invalid UTF-8 name, target escape, or entry-budget overflow
returns `file_list_denied`. Broker result serialization and the existing 64 KiB
exchange budget remain the final output-size boundary.

## Testing

Broker tests cover stable identifiers, declaration/grant/registration/root
gates, deterministic entry types, nested paths, traversal and link rejection,
argument validation, exact entry-budget behavior, metadata failures, and
unchanged first-party grants. SDK tests pin `list_dir()` delegation. Worker e2e
tests prove a granted plugin can list its root and an ungranted plugin receives
the stable `PLUGIN_BROKER_DENIED` lifecycle result.

## Non-Goals

- Recursive traversal, globbing, pagination, file content, file metadata beyond
  entry type, writes, deletes, watches, and host-global directory access.
- A new `file_list` Manifest permission.
- Changes to the Worker wire protocol or default first-party grants.
