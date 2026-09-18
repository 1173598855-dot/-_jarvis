# Terminal Worker Response Protocol Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make TerminalWorker reject malformed or miscorrelated child responses without changing valid fixed-operation behavior.

**Architecture:** The parent keeps ownership of command correlation and parses the existing one-response JSON wire value with strict duplicate-key, constant, schema, type, and invariant checks. Protocol failures reuse the existing unsuccessful `TerminalResult`; valid stdout and stderr remain bounded after validation.

**Tech Stack:** Python 3.10+, standard-library `json`, `math`, `datetime`, unittest.

## Global Constraints

- Preserve the fixed `echo`, `pwd`, `whoami`, `hostname`, and `date` operations.
- Preserve the child request and public HTTP response shapes.
- Reject malformed wire values without including their contents in errors.
- Add no dependencies and no terminal execution authority.
- Do not stage, commit, reset, clean, or revert the mixed worktree.

---

### Task 1: Strict Response Regression

**Files:**
- Modify: `tests/test_terminal_worker.py`

**Interfaces:**
- Consumes: `TerminalWorker._decode_result(cmd: TerminalCommand, payload: str) -> TerminalResult`
- Produces: regressions requiring malformed responses to retain the parent command ID/risk and return `success=False`

- [x] **Step 1: Add a valid response fixture**

Add `_worker_payload(**overrides)` that returns the exact eight response fields
with command ID `wire`, exit code `0`, string output fields, duration `0.1`,
boolean success, `safe` risk, and a parseable timestamp. Serialize ordinary
cases with `json.dumps`.

- [x] **Step 2: Add coercion and invariant cases**

For a `TerminalCommand(id="wire", command="echo", risk_level=SAFE)`, assert
each payload below returns the existing protocol failure instead of success:

```python
{"success": "false"}
{"exit_code": 0.5}
{"duration": -0.1}
{"timestamp": "not-a-timestamp"}
{"success": False, "exit_code": 0}
```

- [x] **Step 3: Add schema and correlation cases**

Assert missing `timestamp`, unknown `extra`, mismatched `command_id`, mismatched
`risk_level`, duplicate `success` keys, `duration: NaN`, and a 5,000-level JSON
array all fail with the original command ID and `safe` risk.

- [x] **Step 4: Verify RED**

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_terminal_worker.TestTerminalWorker -v
```

Expected: the new subtests fail because the existing decoder coerces or ignores
the malformed values and accepts correlation drift.

### Task 2: Exact Parent Decoder

**Files:**
- Modify: `src/core/kernel/terminal_worker.py`
- Modify: `tests/test_terminal_worker.py`

**Interfaces:**
- Consumes: the current eight-field child JSON response and parent `TerminalCommand`
- Produces: a validated `TerminalResult` or the existing parent-correlated protocol failure

- [x] **Step 1: Parse strict JSON**

Import `math`. Add a duplicate-key object hook and a JSON-constant rejector,
then call `json.loads` with both hooks. Require the decoded root to be a built-in
dictionary with exactly the eight expected keys, and convert decoder recursion
exhaustion into the same protocol failure.

- [x] **Step 2: Validate exact values and invariants**

Require exact built-in field types, finite non-negative duration, matching
command ID/risk, consistent success/exit code, and a parseable non-empty ISO
timestamp. Raise `ValueError` with bounded structural messages on rejection.

- [x] **Step 3: Construct only from validated values**

Remove `str`, `int`, `float`, and `bool` coercion. Keep stdout/stderr slicing,
the response byte bound, and the existing failure catch. Update the mocked valid
timestamp in the environment-isolation test to the fixture timestamp.

- [x] **Step 4: Verify GREEN**

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_terminal_worker tests.test_terminal_executor tests.test_terminal_executor_extended -v
```

Expected: all focused terminal tests pass, including real child execution.

### Task 3: Review, Full Evidence, And Ledger

**Files:**
- Modify: `AGENTS.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/reports/PROJECT_ANALYSIS.md`
- Modify: `docs/reports/README.md`
- Create: `docs/reports/AUDIT_REPORT_152.md`
- Delete: `docs/reports/AUDIT_REPORT_142.md`

**Interfaces:**
- Consumes: final strict decoder, regression results, and fresh verification totals
- Produces: Iteration 152 evidence and rolling report window 143-152

- [x] **Step 1: Self-review protocol and scope**

Confirm every response field is required exactly once, no coercion remains,
errors exclude raw payload values, correlation stays parent-owned, valid child
output is unchanged, and no public authority or dependency changed.

- [x] **Step 2: Run complete project gates**

```powershell
.\venv\Scripts\python.exe tests\run_all.py
.\venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
.\venv\Scripts\python.exe -m compileall -q src tests scripts
.\venv\Scripts\python.exe -m ruff check src tests scripts
Set-Location frontend
npm test -- --run
$env:JARVIS_E2E_PORT = "5174"
npm run test:e2e
npm run typecheck
npm run build
Set-Location ..
.\venv\Scripts\python.exe scripts\ci_local_integration.py --require-services
git diff --check
```

- [x] **Step 3: Update Iteration 152 evidence and rolling window**

Record fresh totals, add `AUDIT_REPORT_152.md`, remove only report 142, update
current-state documents, and mark every plan checkbox complete.

- [x] **Step 4: Run final guards**

Run the focused terminal tests, iteration-ledger/docs guards, Ruff,
`git diff --check`, repository `.test-*` checks, and `git status --short`.
