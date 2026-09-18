# Bounded Plugin Discovery Entries Design

## Goal

Prevent `PluginLoader.discover_plugins()` from materializing or traversing an
unbounded plugin-root directory. Discovery accepts at most 8,192 direct entries
and rejects the whole snapshot at the first additional entry before reading any
`manifest.json` content.

## Context and options

Plugin manifest reads already have a 64 KiB byte boundary, but discovery first
calls `sorted(self.plugins_dir.iterdir())`. A plugin root with an excessive
number of direct children can therefore consume unbounded memory and sorting
work before any manifest validation runs. Three approaches were considered:

1. Process entries as the directory iterator yields them. This avoids one full
   list but leaves traversal and manifest IO unbounded and removes deterministic
   name ordering.
2. Retain only the first 8,192 sorted candidates. This bounds memory but still
   scans the entire directory and silently returns an incomplete plugin set.
3. Collect no more than 8,192 direct entries, stop at the first overflow, and
   reject the whole discovery snapshot. This bounds memory and traversal work
   while keeping successful discovery deterministic. This is the selected
   approach.

## Architecture and data flow

`src/core/kernel/plugin_sdk.py` exposes
`MAX_PLUGIN_DISCOVERY_ENTRIES = 8_192`. A focused Loader helper owns one
`os.scandir()` context, appends direct entry paths until the fixed budget is
exhausted, raises `OverflowError` on the first additional entry, and sorts only
the bounded list by path name.

`discover_plugins()` obtains the complete bounded candidate list before opening
any manifest. An unreadable root or candidate overflow replaces the Loader-owned
`_manifests` snapshot with an empty list and returns it. This preserves the
method's existing fail-closed list result and prevents partial results from
being mistaken for a complete repository view. At or below the limit, symlink,
direct-root, manifest-size, schema, and sandbox checks retain their current
per-candidate isolation.

The limit counts every direct directory entry, not only plugin directories.
Ignoring regular files or links before accounting would allow an attacker or
damaged repository to retain an unbounded root scan.

## Error handling and compatibility

Candidate overflow is a discovery-level integrity failure rather than a
malformed individual plugin. It is logged without entry names or manifest
payloads, produces no Worker activity, and exposes no new HTTP error contract.
Successful discovery retains deterministic name ordering and continues to skip
invalid siblings independently.

No dependency, configuration key, plugin manifest field, lifecycle operation,
or OS-level filesystem/network sandbox is introduced by this iteration.

## Testing

Regression tests patch the entry budget to a small value and prove that:

- exactly the configured number of entries remains discoverable and sorted;
- one additional entry returns an empty snapshot and no manifest is read;
- the `os.scandir()` iterator is not advanced after the first over-budget
  entry; and
- a previous successful Loader-owned snapshot is cleared after overflow.

The focused Plugin SDK suites, aggregate and discovery Python suites, compile
check, Ruff, integration profile, iteration ledger, and diff whitespace check
provide the iteration evidence.

