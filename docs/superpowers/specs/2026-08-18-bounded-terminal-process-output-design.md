# Bounded Terminal Process Output Design

## Problem

`TerminalExecutor` and the parent side of `TerminalWorker` call
`subprocess.Popen.communicate()` and truncate the returned strings afterward.
The visible result is bounded, but a command or compromised worker can make
the parent retain arbitrary stdout/stderr before truncation.

## Decision

- Read binary stdout and stderr concurrently in dedicated daemon reader
  threads, using a fixed 8 KiB read chunk.
- Give each stream an independent raw-byte budget. `TerminalExecutor` uses an
  8 MiB budget per stream; `TerminalWorker` uses its existing 64 KiB worker
  response budget for stdout and an 8 KiB diagnostic budget for stderr.
- Retain only the prefix within the budget. The first byte beyond either limit
  sets an overflow flag and the parent kills the child before returning a
  failure. A short polling loop checks overflow while preserving the existing
  command timeout.
- Decode only the bounded bytes with UTF-8 replacement, then apply the existing
  visible `max_output_size`/stderr slicing. Timeout and non-zero exit behavior
  remain unchanged.
- Keep a small `communicate()` compatibility fallback only when unit-test
  doubles do not expose real byte streams; production `Popen` paths always use
  the bounded reader.

## Alternatives

1. Post-check `communicate()` output was rejected because it already retains the
   untrusted output in memory.
2. Redirecting to temporary files was rejected because it moves the unbounded
   resource risk to disk and complicates cleanup/ownership.
3. Reading one pipe at a time was rejected because a child writing both streams
   can deadlock before the second pipe is drained.

## Compatibility

Successful command output and existing `TerminalResult` fields remain
unchanged after the existing visible prefix truncation. Timeout results keep
their current `exit_code=-1` and timeout stderr. A new internal bounded-output
failure is returned as `success=False`, `exit_code=-1`, with the bounded prefix
and a stable diagnostic; HTTP routes continue to expose their existing worker
error envelopes.

## Verification Contract

- A child emitting 8 MiB plus one byte on stdout or stderr is killed at the
  first over-limit byte and cannot resolve successfully.
- Exactly-at-limit output remains successful and is decoded only after close.
- A late process close/error after overflow cannot replace the bounded failure.
- Worker responses over 64 KiB fail before full JSON decoding, while valid
  worker responses and timeout handling preserve existing tests.
