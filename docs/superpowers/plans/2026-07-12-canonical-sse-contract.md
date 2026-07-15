# Canonical SSE Contract Implementation Plan

> **For agentic workers:** Execute this plan inline. The active user instruction is a continuous development request, so do not pause for a handoff choice.

**Goal:** Make GET /api/ollama/chat/stream a declared, deterministic cross-service contract with canonical content, error, and terminal frames.

**Architecture:** contracts/core-api.openapi.json remains the wire-contract source. Python HTTPServer and FastAPI already produce logical {model, content, done} frames; both will use the same nested error envelope. Express will translate native Ollama NDJSON/SSE input into that format instead of exposing message.content. The Solid client will consume only the canonical format.

**Tech Stack:** Python 3 standard library, FastAPI, Express 5, OpenAPI 3.1 JSON, Vitest, unittest, and the existing loopback Ollama fixture.

## Global Constraints

- Add no runtime or development dependency.
- Keep all test networking on 127.0.0.1 and dynamic ports.
- A successful stream emits canonical JSON frames and exactly one final data: [DONE] marker.
- An upstream, parsing, or generator error emits exactly one nested error frame and never emits [DONE].
- Preserve native Ollama token counters in canonical frames so session usage accounting and the browser callback remain correct.
- Do not stage or commit this dirty shared worktree.
- Update PROJECT_ANALYSIS.md, CHANGELOG.md, the report index, and AUDIT_REPORT_112.md; retain reports 103-112 only.

---

### Task 1: Declare and Reproduce the Shared Stream Contract

**Files:**

- Modify: contracts/core-api.openapi.json
- Modify: tests/test_api_contract.py
- Modify: frontend/server.test.js

**Interfaces:**

- Consumes: _OllamaFixtureHandler, _assert_json_shape, and Express’s loopback fixture.
- Produces: SseContentFrame, SseErrorFrame, and a declared GET /api/ollama/chat/stream response using text/event-stream.

- [x] **Step 1: Write failing contract and live-stream tests**

Add a contract test that asserts the stream operation exists and includes text/event-stream, then read each service body into data: payloads. Validate this representative content object:

    content_frame = {
        "model": "fixture-model:latest",
        "content": "OK",
        "done": False,
        "prompt_eval_count": 10,
        "eval_count": 7,
    }
    _assert_json_shape(self, contract, content_schema, content_frame)

Configure _OllamaFixtureHandler to return two NDJSON frames when the request includes "stream": true; the first contains text and the second has done: true. Assert every Python and Express stream has one done: true JSON frame followed by exactly one [DONE] marker.

In frontend/server.test.js, assert a missing model produces:

    expect(body).toContain('"code":"OLLAMA_STREAM_ERROR"');
    expect(body).not.toContain('data: [DONE]');

- [x] **Step 2: Run the focused tests and observe red**

Run:

    .\venv\Scripts\python.exe -m unittest tests.test_api_contract.TestSharedApiContract.test_stream_contract_is_declared
    .\venv\Scripts\python.exe -m unittest tests.test_api_contract.TestSharedApiContract.test_all_implementations_match_stable_response_schemas

Run from frontend:

    npm test -- --run server.test.js

Expected: the contract test fails because the stream path is missing and the Express error test fails because the adapter emits a string error plus [DONE].

- [x] **Step 3: Add the OpenAPI event schemas**

Declare GET /api/ollama/chat/stream with optional model and messages query parameters and a 200 text/event-stream response. Add SseContentFrame with required model, content, and done properties; optional prompt_eval_count and eval_count are non-negative integers. Add SseErrorFrame with required error.code and error.message strings. Set info.version to 1.4.0.

- [x] **Step 4: Verify the declaration test**

Run:

    .\venv\Scripts\python.exe -m unittest tests.test_api_contract.TestSharedApiContract.test_stream_contract_is_declared

Expected: PASS; the test resolves both event schemas from the contract.

### Task 2: Normalize Server Frames and Browser Consumption

**Files:**

- Modify: src/main.py
- Modify: src/main_fastapi.py
- Modify: frontend/server.js
- Modify: frontend/src/services/chat-stream.ts
- Modify: frontend/src/tests/chat-stream.test.ts
- Modify: tests/test_main.py
- Modify: tests/test_main_fastapi.py

**Interfaces:**

- Consumes: stream_chat_generator(model, messages) returning tuples of chunk text and done state, and native Ollama NDJSON input.
- Produces: content events with model, content, done, prompt_eval_count?, and eval_count?; nested errors with code OLLAMA_STREAM_ERROR; at most one terminal marker per successful response.

- [x] **Step 1: Write failing adapter and client tests**

Create Python handler tests that force stream_chat_generator to raise and assert the serialized event has the nested error shape and no terminal marker. Add a browser parsing test that sends canonical content plus token counters and expects:

    expect(onDelta).toHaveBeenCalledWith('hello');
    expect(onUsage).toHaveBeenCalledWith({ prompt: 7, completion: 5 });

Add an error frame containing error code OLLAMA_STREAM_ERROR and message offline, then assert the client rejects with that exact code.

- [x] **Step 2: Run the focused tests and observe red**

Run:

    .\venv\Scripts\python.exe -m unittest tests.test_main tests.test_main_fastapi

Run from frontend:

    npm test -- --run src/tests/chat-stream.test.ts server.test.js

Expected: FAIL because Python errors are string payloads, Express leaks native frames, and the browser parser only reads message.content.

- [x] **Step 3: Implement the minimal normalizers**

In both Python generators, replace the exception event with:

    error_data = json.dumps({
        "error": {"code": "OLLAMA_STREAM_ERROR", "message": str(error)},
    }, ensure_ascii=False)
    yield f"data: {error_data}\n\n"

Track completed = False, set it after a done: true content frame, and emit [DONE] only when completed is true. In Express, parse each upstream line, call tokenUsage.recordFrame(frame), and emit:

    const normalized = {
      model: frame.model || payload.model,
      content: frame.message?.content ?? frame.content ?? '',
      done: frame.done === true,
    };

Copy finite prompt_eval_count and eval_count fields. Use one emitStreamError(message) function that writes the nested error envelope, marks the response failed, and prevents terminal completion. Update processEvent to consume frame.content while retaining token-counter handling.

- [x] **Step 4: Verify stream behavior and accounting**

Run:

    .\venv\Scripts\python.exe -m unittest tests.test_main tests.test_main_fastapi tests.test_api_contract

Run from frontend:

    npm test -- --run server.test.js src/tests/chat-stream.test.ts

Expected: PASS. Success has one terminal marker, errors do not terminate as successful, and token totals still contain 12 for the Express fixture.

### Task 3: Record Iteration 112 and Run the Delivery Gate

**Files:**

- Modify: AGENTS.md
- Modify: CHANGELOG.md
- Modify: docs/reports/GITHUB_LEARNING_REPORT.md
- Modify: docs/reports/PROJECT_ANALYSIS.md
- Modify: docs/reports/README.md
- Create: docs/reports/AUDIT_REPORT_112.md
- Delete: docs/reports/AUDIT_REPORT_102.md

**Interfaces:**

- Consumes: current test counts and the successful GitHub metadata review for Schemathesis and Spectral.
- Produces: a rolling 103-112 ledger with actual verification evidence.

- [x] **Step 1: Record Phase 3 research and risk reduction**

Append the public GitHub results from 2026-07-12: Schemathesis 3,452 stars/MIT and Spectral 3,151 stars/Apache-2.0, both active and not archived. Record the no-dependency decision because deterministic loopback tests now cover the declared stream contract.

- [x] **Step 2: Update reports and remove the oldest audit report**

Write AUDIT_REPORT_112.md with final commands and actual counts. Put Iteration 112 at the start of CHANGELOG.md, change the report index to 103-112, and delete AUDIT_REPORT_102.md. Keep PROJECT_ANALYSIS.md focused on remaining Git/proxy error schemas and real-Ollama strict-mode verification.

- [x] **Step 3: Run the full delivery gate**

Run:

    .\venv\Scripts\python.exe tests\run_all.py
    .\venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
    .\venv\Scripts\python.exe -m compileall -q src tests scripts

Run from frontend:

    npm test -- --run
    npm run test:e2e
    npm run typecheck
    npm run build

Finally run:

    git diff --check
    git status --short

Expected: every test/build command passes; Playwright retains only the documented desktop-condition skip; the report window contains exactly ten files numbered 103-112.
