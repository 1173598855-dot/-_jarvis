# AUDIT_REPORT_253.md

**Iteration**: #253
**Date**: 2026-09-30
**Status**: Complete

## Scope

This iteration delivers the next Phase F work package: optional local-embedding
semantic retrieval over the migratable SQLite memory index. The feature is
disabled by default — semantic mode requires a server-configured embedding
model via `JARVIS_MEMORY_EMBED_MODEL`; without it the endpoint returns a
stable 503 envelope instead of silently degrading. The Markdown store stays
the single source of truth, vectors are derived data keyed to entry content
hashes, and no execution authority is added: the provider is a bounded
loopback HTTP client, and the index remains a read-path adapter.

## Changes

- Added the `EmbeddingProvider` port in `core/contracts/embedding_provider.py`:
  bounded batches (max 32 texts, 8 KiB per text), validated model ids, and a
  fail-closed response validator (consistent dimensions, max 4096, finite
  numeric values only).
- Added the `OllamaEmbeddingProvider` adapter (`adapters/ollama_embedding.py`)
  calling the local `POST /api/embed` endpoint with `OLLAMA_BASE_URL`
  conventions, bounded 8 MiB response reads, and an opt-in
  `embedding_provider_from_env()` factory that returns `None` when the model
  environment variable is unset and raises on invalid configuration.
- Bumped the index schema to version 3 with a `memory_vectors` table keyed by
  `(entry_id, model_id)` and carrying the `content_hash` it was computed
  from. Older schema versions reset transparently (derived data); reconcile
  now also purges vectors whose entry disappeared.
- Added `vector_backlog`, `store_vectors` (normalized float32 packing) and
  `search_semantic` (pure-stdlib cosine ranking over hash-current vectors,
  dimension-mismatch rows skipped, deterministic title/id tie-breaks).
- Extended `GET /api/memory/search` with `mode=semantic` across the stdlib
  HTTPServer, FastAPI and the Express bridge: the bounded backlog (32 per
  request) is embedded before the query, partial coverage is reported
  honestly via a `coverage: {vectors, entries}` field, and results include
  the cosine similarity as the score. Stable 503 envelopes distinguish
  `MEMORY_SEMANTIC_UNAVAILABLE` from `MEMORY_INDEX_UNAVAILABLE`.
- Documented the parameter, `coverage` and mode enum in
  `contracts/core-api.openapi.json`.
- Added 23 focused tests (port bounds, Ollama adapter against a local fixture
  HTTP server, vector coverage/staleness/ranking/validation, and semantic
  end-to-end flows with a scripted provider), and registered the two new
  test classes in the aggregate suite.

## Verification

| Command | Result |
|---|---|
| `python -m unittest tests.test_sqlite_memory_index -v` | 54 passed |
| `python tests/run_all.py` | Total: 1228; passed: 1217; skipped: 11 |
| `python -m unittest tests.test_api_contract` | 31 passed |
| `python -m compileall -q src tests scripts` | Passed |
| `python -m ruff check src tests scripts` | Passed |
| `git diff --check` | Passed |

## Residual Risk

- The Ollama adapter is verified against a local fixture HTTP server, not a
  live Ollama daemon; a real-model integration profile remains follow-up.
- Semantic search reports partial coverage while the backlog catches up
  (32 embeds per request); consumers must read `coverage` to know when
  results span the whole indexed set.
- Pure-stdlib cosine ranking over very large stores (approaching the 8,192
  row budget at high dimensionality) has not been performance-profiled.
- Local embeddings embed the first 8 KiB of each entry body, so very long
  entries are represented by their prefix; the limit is documented rather
  than silent because the port rejects oversized inputs.
- `MemoryRepository` contract convergence remains the remaining Phase F work
  package.
