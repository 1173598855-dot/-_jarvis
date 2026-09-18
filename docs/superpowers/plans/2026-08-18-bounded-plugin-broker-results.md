# Bounded Plugin Broker Results Implementation Plan

> **For agentic workers:** Execute inline in this session with TDD and review
> each task before continuing.

**Goal:** Reject oversized Plugin Broker handler results before canonical JSON
serialization allocates a complete temporary copy.

**Architecture:** Add one exact, capped canonical-JSON size helper beside the
existing Plugin Worker serializer, then use it at the only unframed handler
result boundary. Preserve all existing wire and Broker contracts.

**Tech Stack:** Python standard library, `unittest`, `tracemalloc`.

## Global Constraints

- `MAX_BROKER_EXCHANGE_BYTES` remains 65,536 bytes.
- Exact-limit canonical JSON values remain valid.
- Oversized handler results retain the stable `result_too_large` denial.
- No Plugin Worker schema, handler signature, or event commit behavior changes.

---

### Task 1: Exact bounded canonical JSON sizing

**Files:**
- Modify: `src/core/contracts/plugin_worker_protocol.py`
- Test: `tests/test_plugin_worker_protocol.py`

**Interfaces:**
- Produces `bounded_stable_json_size(value: Any, max_bytes: int) -> int`.
- Raises `PluginWorkerProtocolError` for malformed JSON values.
- Raises `OverflowError` at the first canonical byte beyond `max_bytes`.

- [ ] Add tests comparing the helper with `len(stable_json_bytes(value))` for
  primitives, nested objects, escaped controls, and Unicode.
- [ ] Add exact-limit, one-byte overflow, invalid-limit, and malformed-value
  tests; run them and confirm RED from the missing helper.
- [ ] Implement scalar, string, mapping, and sequence counters with the existing
  depth and integer constraints, stopping as soon as the cap is crossed.
- [ ] Run `python -m unittest tests.test_plugin_worker_protocol -q` and confirm
  GREEN.

### Task 2: Bound handler-result accounting

**Files:**
- Modify: `src/core/kernel/plugin_broker.py`
- Test: `tests/test_plugin_broker.py`

**Interfaces:**
- Consumes `bounded_stable_json_size(result, MAX_BROKER_EXCHANGE_BYTES)`.
- Preserves `handler_result_invalid` and `result_too_large` results.

- [ ] Add a regression that returns a multi-megabyte string from a registered
  handler, traces allocations only during `handle()`, and asserts a bounded peak
  plus the existing `result_too_large` denial.
- [ ] Run the focused test and confirm RED because full serialization allocates
  proportional temporary storage.
- [ ] Replace only handler-result `stable_json_bytes()` sizing with the capped
  helper and map `OverflowError` to `result_too_large`.
- [ ] Run Plugin Broker and protocol tests and confirm GREEN.

### Task 3: Review, documentation, and verification

**Files:**
- Modify: `AGENTS.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/DEVELOPMENT_GUIDE.md`
- Modify: `docs/reports/PROJECT_ANALYSIS.md`
- Modify: `docs/reports/README.md`
- Create: `docs/reports/AUDIT_REPORT_199.md`

- [ ] Review the scoped diff for exact sizing, exception precedence, event
  staging, API compatibility, and unrelated changes.
- [ ] Record Iteration 199 behavior and fresh verification evidence.
- [ ] Run targeted tests, aggregate suite, full discovery, Ruff, compileall,
  required local integration, and `git diff --check`.
