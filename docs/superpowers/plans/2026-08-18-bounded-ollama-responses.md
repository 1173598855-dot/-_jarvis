# Bounded Ollama Responses Plan

**Goal:** Make Ollama and optional local integration response reads fail closed
at explicit byte boundaries without changing valid response contracts.

1. Add RED tests for bounded non-streaming, streaming, and integration profile
   responses, including `Content-Length` strings.
2. Add bounded chunk/line readers to `OllamaManager` and route GET, POST, pull,
   and chat stream paths through them.
3. Add one bounded response reader to the integration profile and reuse it for
   JSON, HTTP errors, and SSE payloads.
4. Include the new Ollama boundary suite in the aggregate runner.
5. Run targeted tests, local integration, aggregate/discovery suites, Ruff,
   compileall, and diff checks; then record the audit evidence.
