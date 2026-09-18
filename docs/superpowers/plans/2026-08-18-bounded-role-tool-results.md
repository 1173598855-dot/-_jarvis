# Bounded Role Tool Results Implementation Plan

> **For agentic workers:** Execute inline with TDD and review each task before
> continuing.

**Goal:** Bound Role Tool argument and result accounting before complete JSON
serialization while preserving existing protocol and budget behavior.

**Architecture:** Add one exact capped-size helper beside the Role Tool
serializer and invoke it at the Broker's two unframed size checks. Values that
fit still use the existing validation and replay-record normalization path.

**Tech Stack:** Python standard library, `unittest`, `tracemalloc`.

## Global Constraints

- `RoleToolBudget` defaults remain 8,192 argument bytes and 16,384 result bytes.
- Exact-limit canonical values remain valid.
- Existing denial reasons and invocation record shapes remain unchanged.
- No new JSON depth or integer limits are introduced in the Role Tool contract.

---

### Task 1: Exact bounded Role Tool JSON sizing

**Files:**
- Modify: `src/core/contracts/role_tool_protocol.py`
- Test: `tests/test_role_tool_protocol.py`

**Interfaces:**
- Produces `bounded_stable_json_size(value: Any, max_bytes: int) -> int`.
- Raises `RoleToolProtocolError` for unsupported, non-finite, or invalid
  Unicode values.
- Raises `OverflowError` at the first canonical byte beyond `max_bytes`.

- [ ] Add canonical differential, exact-limit, one-byte overflow, limit-type,
  and malformed-value tests; run them and confirm RED.
- [ ] Implement incremental scalar, string, mapping, and sequence counting
  using the Role Tool serializer's existing JSON type support.
- [ ] Run `python -m unittest tests.test_role_tool_protocol -q` and confirm
  GREEN.

### Task 2: Bound Broker arguments and results

**Files:**
- Modify: `src/core/brain/role_tools.py`
- Test: `tests/test_role_tools.py`

**Interfaces:**
- Consumes `bounded_stable_json_size()` for call arguments and handler results.
- Preserves `argument_too_large`, `result_too_large`, `invalid_arguments`, and
  `invalid_result` outcomes.

- [ ] Add a traced multi-megabyte handler-result regression and assert no
  invocation is recorded as allowed and no full serialization-sized allocation
  occurs.
- [ ] Run it and confirm RED against the old full-serialization path.
- [ ] Replace only the two pre-budget size calls with the capped helper and map
  `OverflowError` to the existing denial reasons.
- [ ] Run Role Tool protocol/Broker tests and confirm GREEN.

### Task 3: Review, documentation, and verification

**Files:**
- Modify: `AGENTS.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/DEVELOPMENT_GUIDE.md`
- Modify: `docs/reports/PROJECT_ANALYSIS.md`
- Modify: `docs/reports/README.md`
- Create: `docs/reports/AUDIT_REPORT_200.md`

- [ ] Review size semantics, exception precedence, replay records, and scoped
  diff.
- [ ] Record Iteration 200 evidence and run all required verification commands.
