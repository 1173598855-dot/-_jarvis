# Bounded Local Ollama Fixture Request Body

**Goal:** Bound the local integration fixture's declared request body before
JSON parsing without changing valid fixture responses.

## Task 1: Add RED regression

- Provide an oversized declared length and a stream that fails if read; assert
  the helper rejects it before touching the stream.

## Task 2: Implement the helper

- Add the 32 KiB fixture budget and validate length, stream bytes and object JSON.
- Route `do_POST` through the helper while preserving the existing 400 response
  and valid tool-call behavior.

## Task 3: Verify and document

- Run focused fixture tests, aggregate/discovery suites, compileall, Ruff,
  frontend checks, required-services integration, ledger and diff checks.
- Synchronize the Iteration 211 audit report and current-state docs.
