# Express Git Error Envelope Implementation Plan

> **For agentic workers:** Execute this plan inline with executing-plans. The project’s automatic continuous-iteration protocol authorizes inline progress and the shared dirty worktree must not be staged or committed.

**Goal:** Return stable ErrorResponse objects when Express cannot execute Git metadata commands.

**Architecture:** Add an environment-derived GIT_COMMAND server configuration with default value git. runGitCommand will reject child-process spawn errors, and all three Git routes will translate every rejected command into sendApiError with GIT_COMMAND_FAILED. The existing end-to-end Express fixture will use a nonexistent trusted executable to exercise the real process boundary.

**Tech Stack:** Node.js child_process, Express 5, Vitest, and existing JARVIS ErrorResponse conventions.

## Global Constraints

- Add no runtime or development dependency.
- Do not accept a Git executable from a request, query string, or browser client.
- Default behavior must keep the trusted command git.
- Error responses are { error: { code, message } }; the message must not include a raw executable error.
- Do not stage or commit the shared dirty worktree.
- Record Iteration 113 only after actual full verification results are available.

---

### Task 1: Red Test for Git Process Failure

**Files:**

- Modify: frontend/server.test.js

**Interfaces:**

- Consumes: the existing spawned Express fixture and its env object.
- Produces: an integration assertion that GET /api/git/status returns HTTP 500 and ErrorResponse when JARVIS_GIT_COMMAND names no executable.

- [x] **Step 1: Configure the existing fixture with a deterministic missing executable**

Add this environment item in beforeAll:

    JARVIS_GIT_COMMAND: 'jarvis-git-command-does-not-exist',

Add this test:

    test('returns a stable envelope when Git cannot start', async () => {
      const response = await fetch(
        'http://127.0.0.1:' + apiPort + '/api/git/status',
      );
      const body = await response.json();

      expect(response.status).toBe(500);
      expect(body).toEqual({
        error: {
          code: 'GIT_COMMAND_FAILED',
          message: 'Git repository metadata is unavailable',
        },
      });
    });

- [x] **Step 2: Run the red test**

Run from frontend:

    npm test -- --run server.test.js

Expected: FAIL because server.js still invokes git unconditionally or terminates on the unhandled child-process error.

### Task 2: Normalize Git Process Failures

**Files:**

- Modify: frontend/server.js
- Modify: frontend/server.test.js
- Modify: docs/SETUP.md

**Interfaces:**

- Consumes: process.env.JARVIS_GIT_COMMAND, runGitCommand(args), and sendApiError(res, status, code, message).
- Produces: GIT_COMMAND_FAILED error envelopes from GET /api/git/status, GET /api/git/log, and GET /api/git/branches.

- [x] **Step 1: Add minimal trusted process configuration**

Near the existing Ollama configuration, add:

    const GIT_COMMAND = process.env.JARVIS_GIT_COMMAND || 'git';

Change runGitCommand to use GIT_COMMAND and safely reject a spawn failure:

    const git = spawn(GIT_COMMAND, args, { cwd: path.join(__dirname, '..') });
    git.once('error', reject);
    git.once('close', (code) => {
      if (code === 0) resolve({ stdout, stderr });
      else reject(new Error(stderr || 'Git command failed'));
    });

Use one completion guard so an error and a subsequent close cannot settle the Promise twice.

- [x] **Step 2: Translate every Git route catch to the public contract**

Replace each Git route catch body with:

    return sendApiError(
      res,
      500,
      'GIT_COMMAND_FAILED',
      'Git repository metadata is unavailable',
    );

Do not return err.message and do not log a request-supplied value.

- [x] **Step 3: Run the green regression**

Run from frontend:

    npm test -- --run server.test.js

Expected: PASS with the server process alive and the exact ErrorResponse object.

- [x] **Step 4: Record operational configuration**

In docs/SETUP.md, document JARVIS_GIT_COMMAND as an optional, trusted process-level override used for controlled deployments and tests. State that it is not exposed through HTTP.

### Task 3: Delivery Gate and Iteration Record

**Files:**

- Modify: AGENTS.md
- Modify: CHANGELOG.md
- Modify: docs/reports/GITHUB_LEARNING_REPORT.md
- Modify: docs/reports/PROJECT_ANALYSIS.md
- Modify: docs/reports/README.md
- Create: docs/reports/AUDIT_REPORT_113.md
- Delete: docs/reports/AUDIT_REPORT_103.md

- [x] **Step 1: Record the GitHub research decision**

Append http-errors (1,558 Stars, MIT, active), zalando/problem (950 Stars, MIT, active), and Schemathesis (3,452 Stars, MIT, active). Record the no-dependency decision.

- [x] **Step 2: Update the rolling ledger**

Create AUDIT_REPORT_113.md only after running the delivery gate. Add Iteration 113 to CHANGELOG.md, update the report index to 104-113, and remove AUDIT_REPORT_103.md.

- [x] **Step 3: Run verification**

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

Expected: every command passes; browser E2E retains only its documented desktop-condition skip; the report window contains exactly ten files numbered 104-113.
