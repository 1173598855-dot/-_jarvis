# Bounded Express Git Output Design

## Problem

Express Git metadata routes collect child-process `stdout` and `stderr` by
appending decoded strings without a byte budget. A repository or configured Git
command can therefore make the BFF retain arbitrary output before the route
parses it or returns an error.

## Decision

- Give one `runGitCommand()` invocation an 8 MiB raw-output budget for each of
  `stdout` and `stderr`.
- Count `Buffer.byteLength` before retaining each child-process chunk, keep
  bounded Buffer chunks, and decode only after a successful process close.
- On the first over-limit chunk, reject with an internal bounded-output error,
  destroy child streams, and kill the child process. Settlement remains
  single-shot when kill emits later `error` or `close` events.
- Keep all three Git routes read-only and preserve their existing public
  `GIT_COMMAND_FAILED` status/envelope. No new HTTP error code is exposed.

## Alternatives

1. Check output length after string concatenation was rejected because it still
   retains the complete untrusted output.
2. Cap only `/api/git/log` by commit count was rejected because status and
   branch output can also grow, and individual Git fields are unbounded.
3. Add a process timeout was deferred because it changes command lifecycle and
   is independent of the confirmed output-retention defect.

## Compatibility

Successful output at or below 8 MiB is decoded with the same UTF-8 text and
route parsing. Existing spawn arguments, configured `JARVIS_GIT_COMMAND`, error
status, and JSON shapes remain unchanged.

## Verification Contract

- A fake child emitting exactly 8 MiB then one additional byte is rejected,
  killed, and never resolves as a successful command.
- Later `close`/`error` events cannot settle the command a second time.
- Existing Express Git success and missing-command envelopes continue to pass,
  along with frontend, Python, lint, build, E2E, and integration gates.

