# Role Tool Authorization Boundary Design

**Iteration:** 128
**Date:** 2026-07-15
**Status:** Approved by the five-iteration autonomous execution directive

## Context

Role profiles declare names such as `terminal_executor`, `plugin_sdk`, and
`security_auditor`, but `AgentFactory` currently labels every declaration as an
available tool in model prompts. No execution path exists, so the label is
misleading, and adding one later without a policy choke point would risk
turning profile metadata into ambient authority.

Iteration 128 establishes the authorization and invocation boundary before any
model-driven tool loop is added. It does not add terminal or plugin access to
the Ollama role handler.

## Phase 3 Evidence

Three focused GitHub searches covered AI-agent tool permissions, LLM capability
sandboxes, and process-isolated agent workers. Two current candidates met the
license, activity, and popularity thresholds:

- `kontext-security/kontext-cli`: 210 Stars, MIT, pushed 2026-07-14. Its Go
  daemon, macOS self-service setup, local judge, and optional hosted event
  stream are much broader than this repository's in-process Python boundary.
- `fu351/Doberman-Core`: 112 Stars, Apache-2.0, pushed 2026-07-12. Its complete
  MCP proxy, adaptive policy engine, authentication flow, storage, and TUI
  duplicate capabilities that are not required for the current role path.

No dependency or upstream source is adopted. The design uses the shared
principles demonstrated by both projects: authorization must be on the actual
execution path, decisions must fail closed, and denied attempts must be
auditable.

## Considered Approaches

### 1. Rename the prompt label only

Change `[AVAILABLE TOOLS]` to `[DECLARED TOOLS]` and keep the declarations as
metadata. This corrects prompt wording but provides no enforceable boundary for
the next iteration.

### 2. Add an in-process policy and broker

Introduce a small standard-library policy object and make a broker the only
supported invocation path. Explicit role grants, profile declarations, and
registered handlers must all intersect before a tool is exposed or invoked.
This follows the repository's local-first, dependency-light architecture and
creates a testable seam for later Ollama tool calling.

### 3. Adopt an external agent-security framework

Kontext and Doberman provide broader runtime governance, but both add another
control plane and lifecycle. Their integration cost and behavior exceed this
iteration's narrow requirement.

**Decision:** Use approach 2.

## Architecture

Create `src/core/brain/role_tools.py` with four public types:

- `RoleToolPolicy` stores explicit per-role grants. Missing roles and missing
  tools are denied. Grants never imply that a handler exists.
- `RoleToolBroker` owns the registered handlers and is the sole invocation
  path. A tool is authorized only when it is declared by the resolved profile,
  explicitly granted to that role, and registered with the broker.
- `RoleToolDecision` is an immutable audit record containing role, tool,
  allowed state, and a stable reason code.
- `RoleToolDeniedError` is raised before handler execution for denied or
  unavailable calls.

The broker keeps a thread-safe bounded decision history. Authorization checks
preserve profile declaration order and de-duplicate names. Callers receive
copies of audit records and cannot mutate internal policy state.

`AgentFactory` accepts an optional broker and otherwise constructs an empty,
default-deny broker. At dispatch time it resolves authorized tools once and:

- stores `declared_tools` and `authorized_tools` separately in task metadata;
- includes `[AUTHORIZED TOOLS]` only when the authorized list is non-empty;
- includes `[TOOL ACCESS] disabled` when no tool is authorized;
- never describes a declared-but-denied tool as available.

The compatibility handler and Ollama handler use the same prompt policy.

## Error Handling And Security Properties

- No wildcard grants or implicit fallback are supported.
- A policy miss, undeclared tool, or unregistered handler denies before any
  handler runs.
- Handler exceptions propagate to the broker caller and are recorded as an
  allowed authorization decision; the broker does not convert execution
  failures into authorization failures.
- Audit storage is bounded to prevent unbounded memory growth.
- This iteration exposes no HTTP endpoint and grants no terminal, plugin,
  filesystem, or network capability by default.

## Testing

Unit tests will first prove the missing behavior:

- empty policy denies every declared tool;
- authorized lists require declaration, explicit grant, and registration;
- denied invocation never calls a handler;
- allowed invocation calls exactly one registered handler;
- audit records use stable reason codes and remain bounded;
- default `AgentFactory` prompts say tool access is disabled;
- an injected broker exposes only its authorized subset and separates task
  metadata into declared and authorized lists.

Focused factory and broker suites run after each red-green cycle. The iteration
then runs the aggregate Python suite, complete discovery, syntax compilation,
frontend tests, browser tests, typecheck, build, and final diff checks.
