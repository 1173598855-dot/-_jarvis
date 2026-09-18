# Bounded Capability Archive Entries Design

## Context

`FileCapabilityStore._verify_archive()` called `ZipFile.infolist()`, which
created a second full list of central-directory metadata before checking the
configured entry limit. It then retained a second `logical_entries` list for
path-conflict validation. The publish path repeated the `infolist()` copy.

## Decision

- Read the already parsed `ZipFile.filelist` directly and reject a list longer
  than `CapabilityPackageLimits.max_files` before any package metadata is
  retained by the adapter.
- Reuse the bounded list for verification and publication; do not call
  `ZipFile.infolist()` in either path.
- Keep names and duplicate detection bounded by the same entry limit.
- Store logical path types in a bounded mapping and run the existing file/
  directory conflict checks after declaration and size validation, preserving
  error precedence for malformed metadata and expanded-size limits.

## Compatibility

The archive, manifest, digest, layout, content-hash, publication, and retry
contracts remain unchanged. Valid archives install as disabled capabilities;
archives over the configured entry limit still return `ARCHIVE_FILE_LIMIT`.

## Scope Boundary

This iteration does not add archive download or HTTP lifecycle inputs, change
ZIP parsing itself, alter package limits, or provide OS-level filesystem or
network isolation.
