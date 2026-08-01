"""
J.A.R.V.I.S. REST API Server - FastAPI version
Resolves Windows WinError 10013 compatibility issues

Run: uvicorn main_fastapi:app --host 127.0.0.1 --port 8080 --reload
Port: 8080

Endpoints:
- GET  /api/health              - Health check
- GET  /api/system/stats        - System statistics
- GET  /api/ollama/status       - Ollama status
- GET  /api/ollama/models       - Installed models
- POST /api/ollama/chat         - Chat request (non-streaming)
- GET  /api/ollama/token-usage  - Token usage snapshot
- GET  /api/ollama/chat/stream  - Streaming chat (SSE)
- GET  /api/plugins             - Plugin list
- POST /api/plugins/load        - Load plugin
- POST /api/plugins/enable      - Enable plugin
- POST /api/plugins/disable     - Disable plugin
- GET  /api/memory/entries      - Memory list
- POST /api/memory/store        - Store memory
- GET  /api/events              - Event history
- GET  /api/orchestrator/agents - Registered agent list
- GET  /api/orchestrator/history - Task history
- POST /api/orchestrator/dispatch - Dispatch task
- GET  /api/roles               - List all roles
- GET  /api/roles/{role_name}   - Get specific role
- POST /api/roles/dispatch      - Dispatch task by role
- POST /api/roles/dispatch_by_cap - Dispatch by capability
"""

import asyncio
import atexit
import json
import logging
import os
import platform
import sys
import threading
import time
import uuid
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict

from adapters.file_run_state_repository import (
    FileRunStateRepository,
    RunStateIntegrityError,
)
from adapters.role_task_record_repository import RoleTaskRecordRepository
from adapters.git_workspace import GitWorkspaceInspector
from app.run_lifecycle import RunLifecycleCoordinator
from core.brain.agent_factory import AgentFactory
from core.brain.context_compressor import MemoryEntry, MemoryStore, MemoryType
from core.brain.orchestrator import AgentTask, Orchestrator
from core.brain.role_dispatch_service import (
    RoleDispatchService,
    RoleTaskTerminationUnconfirmedError,
    RoleWorkerInvalidResultError,
    RoleWorkerUnavailableError,
)
from core.brain.role_worker import (
    RoleWorkerSupervisor,
    WorkerTaskTerminalError,
    apply_worker_token_usage,
    execute_role_task,
)
from core.brain.role_registry import create_default_registry
from core.contracts.worker_protocol import WorkerTaskRequest, WorkerTaskStatus

# Phase 11 imports (moved to top to resolve E402)
from core.kernel.ollama_manager import OllamaManager
from core.kernel.capability_api import (
    CAPABILITY_SNAPSHOT_CACHE_TTL_SECONDS,
    CapabilityRegistryRequestError,
    parse_capability_query_items,
    resolve_capability_registry,
)
from core.kernel.capability_registry import CapabilityRegistry
from core.kernel.capability_resolver import (
    CapabilityResolver,
    CompatibilityTarget,
)
from core.kernel.event_bus import EventBus
from core.kernel.plugin_sdk import (
    FIRST_PARTY_EVENT_GRANTS,
    PLUGIN_API_VERSION,
    PluginManager,
)
from core.kernel.runtime_security import (
    configured_allowed_origins as configured_security_origins,
    terminal_access_enabled,
    terminal_request_is_authorized,
)
from core.kernel.terminal_executor import TerminalCommand, TerminalExecutor
from core.kernel.terminal_policy import TerminalPolicyError, validate_terminal_operation
from core.kernel.terminal_worker import TerminalWorker

# Add src to path (after imports so Phase 11 modules resolve)
sys_path = str(Path(__file__).parent)
if sys_path not in sys.path:
    sys.path.insert(0, sys_path)

logger = logging.getLogger(__name__)
MAX_REQUEST_BODY_BYTES = 32 * 1024
REPOSITORY_ROOT = Path(__file__).resolve().parent.parent


def configured_allowed_origins() -> list[str]:
    return configured_security_origins()


def _normalize_dispatch_text(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None

    normalized = []
    index = 0
    while index < len(value):
        code_point = ord(value[index])
        if 0xD800 <= code_point <= 0xDBFF:
            if index + 1 >= len(value):
                return None
            low_surrogate = ord(value[index + 1])
            if not 0xDC00 <= low_surrogate <= 0xDFFF:
                return None
            scalar = 0x10000 + (
                ((code_point - 0xD800) << 10)
                | (low_surrogate - 0xDC00)
            )
            normalized.append(chr(scalar))
            index += 2
            continue
        if 0xDC00 <= code_point <= 0xDFFF:
            return None
        normalized.append(value[index])
        index += 1
    return "".join(normalized)


class _RequestBodyLimitMiddleware:
    """Reject declared request bodies before framework parsing allocates them."""

    def __init__(self, app, max_body_bytes: int = MAX_REQUEST_BODY_BYTES):
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def _send_limit_response(self, scope, receive, send):
        await JSONResponse(
            status_code=413,
            content={
                "error": {
                    "code": "REQUEST_BODY_TOO_LARGE",
                    "message": "Request body exceeds the 32 KiB limit",
                }
            },
        )(scope, receive, send)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        content_length = dict(scope.get("headers", [])).get(b"content-length")
        if content_length is not None:
            try:
                body_size = int(content_length)
            except ValueError:
                body_size = 0
            if body_size > self.max_body_bytes:
                await self._send_limit_response(scope, receive, send)
                return

        rejected = False
        received_bytes = 0

        async def limited_receive():
            nonlocal rejected, received_bytes
            if rejected:
                return {"type": "http.disconnect"}

            message = await receive()
            if message["type"] != "http.request":
                return message

            received_bytes += len(message.get("body", b""))
            exceeds_limit = received_bytes > self.max_body_bytes
            reaches_limit_with_more_body = (
                received_bytes == self.max_body_bytes
                and message.get("more_body", False)
            )
            if exceeds_limit or reaches_limit_with_more_body:
                rejected = True
                await self._send_limit_response(scope, receive, send)
                return {"type": "http.disconnect"}
            return message

        async def guarded_send(message):
            if not rejected:
                await send(message)

        try:
            await self.app(scope, limited_receive, guarded_send)
        except Exception:
            if not rejected:
                raise

# ============================================================
# FastAPI app initialization
# ============================================================


@asynccontextmanager
async def lifespan(_app: FastAPI):
    app_state = _app.state.jarvis_state
    try:
        try:
            app_state.recovery_outcome = app_state.run_lifecycle.recover_active()
            orphaned = app_state.role_task_repo.load()
            if orphaned:
                recovered = app_state.role_tasks.recover_orphans(orphaned)
                if recovered:
                    logger.info(
                        "Recovered %d orphan role task(s) from previous session",
                        len(recovered),
                    )
                app_state.role_task_repo.clear()

        except RunStateIntegrityError:
            logger.error("RUN_STATE_INTEGRITY_ERROR: startup recovery rejected")
            raise
        logger.info("J.A.R.V.I.S. FastAPI server started on http://127.0.0.1:8080")
        yield
    finally:
        app_state.shutdown()
        logger.info("J.A.R.V.I.S. FastAPI server shutdown complete")


app = FastAPI(
    title="J.A.R.V.I.S. API",
    description="XiaoYi autonomous evolution engine - REST API",
    version="1.1.0",
    lifespan=lifespan,
)

app.add_middleware(_RequestBodyLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=configured_allowed_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-Jarvis-Terminal-Token"],
)


@app.exception_handler(HTTPException)
async def http_exception_handler(_request: Request, exc: HTTPException):
    detail = exc.detail
    if isinstance(detail, dict):
        code = str(detail.get("code", f"HTTP_{exc.status_code}"))
        message = str(detail.get("message", detail))
    else:
        code = f"HTTP_{exc.status_code}"
        message = str(detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": code, "message": message}},
    )


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
):
    errors = exc.errors()
    is_invalid_json = any(
        error.get("type") == "json_invalid" for error in errors
    )
    is_missing_plugin_id = any(
        error.get("type") == "missing"
        and tuple(error.get("loc", ())) == ("body", "plugin_id")
        for error in errors
    )
    is_missing_command = any(
        error.get("type") == "missing"
        and tuple(error.get("loc", ())) == ("body", "command")
        for error in errors
    )
    is_orchestrator_history = request.url.path == "/api/orchestrator/history"
    is_role_task_path = request.url.path.startswith("/api/roles/tasks")
    is_plugin_lifecycle_path = request.url.path in {
        "/api/plugins/load",
        "/api/plugins/enable",
        "/api/plugins/disable",
    }
    status_code = (
        400
        if (
            is_invalid_json
            or is_missing_plugin_id
            or is_missing_command
            or is_orchestrator_history
            or is_role_task_path
            or is_plugin_lifecycle_path
            or request.url.path == "/api/terminal/execute"
            or request.url.path == "/api/ollama/chat/stream"
        )
        else 422
    )
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": (
                    "INVALID_JSON"
                    if is_invalid_json
                    else "MISSING_PLUGIN_ID"
                    if is_missing_plugin_id
                    else "MISSING_COMMAND"
                    if is_missing_command
                    else "INVALID_REQUEST"
                    if is_orchestrator_history
                    else "INVALID_REQUEST"
                ),
                "message": (
                    "Request body must be valid JSON"
                    if is_invalid_json
                    else "Missing plugin_id parameter"
                    if is_missing_plugin_id
                    else "Missing command parameter"
                    if is_missing_command
                    else "The history limit must be an integer"
                    if is_orchestrator_history
                    else "Request body is invalid"
                ),
            }
        },
    )

# ============================================================
# Global state
# ============================================================

class AppState:
    """Application global state"""
    def __init__(
        self,
        memory_dir: str = ".auto-memory",
        terminal=None,
        run_lifecycle: RunLifecycleCoordinator | None = None,
        role_tasks: RoleWorkerSupervisor | None = None,
        role_dispatch: RoleDispatchService | None = None,
        capability_registry: CapabilityRegistry | None = None,
        capability_resolver: CapabilityResolver | None = None,
        capability_target: CompatibilityTarget | None = None,
        event_bus: EventBus | None = None,
        plugin_manager: PluginManager | None = None,
    ):
        if role_dispatch is not None:
            dispatch_supervisor = role_dispatch.supervisor
            if role_tasks is None:
                role_tasks = dispatch_supervisor
            elif role_tasks is not dispatch_supervisor:
                raise ValueError(
                    "role_tasks and role_dispatch must share the same supervisor"
                )
        self.ollama = OllamaManager()
        self.terminal = terminal if terminal is not None else TerminalWorker()
        self.memory_store = MemoryStore(memory_dir=memory_dir)
        self.orchestrator = Orchestrator()
        self.role_registry = create_default_registry()
        self.agent_factory = AgentFactory(
            registry=self.role_registry,
            orchestrator=self.orchestrator,
            ollama_manager=self.ollama,
        )
        if role_tasks is None:
            role_tasks = RoleWorkerSupervisor(
                execute_role_task,
                runner_config={
                    "ollama_base_url": self.ollama.base_url,
                    "role_model": self.agent_factory._role_model,
                    "memory_dir": str(Path(memory_dir).resolve()),
                    "repository_root": str(Path.cwd().resolve()),
                },
                on_terminal=lambda record: apply_worker_token_usage(
                    record,
                    self.ollama,
                ),
            )
        self.role_tasks = role_tasks
        self.role_dispatch = (
            role_dispatch
            if role_dispatch is not None
            else RoleDispatchService(self.role_registry, self.role_tasks)
        )
        self.capability_registry = (
            capability_registry
            if capability_registry is not None
            else CapabilityRegistry(
                REPOSITORY_ROOT,
                cache_ttl_seconds=CAPABILITY_SNAPSHOT_CACHE_TTL_SECONDS,
            )
        )
        self.capability_resolver = (
            capability_resolver
            if capability_resolver is not None
            else CapabilityResolver()
        )
        self.capability_target = (
            capability_target
            if capability_target is not None
            else CompatibilityTarget(
                python=platform.python_version(),
                jarvis_api=PLUGIN_API_VERSION,
            )
        )
        self.event_bus = event_bus if event_bus is not None else EventBus()
        self.plugin_manager = (
            plugin_manager
            if plugin_manager is not None
            else PluginManager(
                event_bus=self.event_bus,
                grants=FIRST_PARTY_EVENT_GRANTS,
            )
        )
        if run_lifecycle is None:
            repository = FileRunStateRepository(
                Path(memory_dir),
                key_provider=self._run_state_key,
            )
            run_lifecycle = RunLifecycleCoordinator(
                repository,
                GitWorkspaceInspector(Path.cwd()),
            )
        self.run_lifecycle = run_lifecycle
        self.recovery_outcome = None
        self.role_task_repo = RoleTaskRecordRepository(Path(memory_dir))

        self.start_time = time.time()
        self.request_count = 0
        self._shutdown_lock = threading.Lock()
        self._shutdown_completed: set[str] = set()

    @staticmethod
    def _run_state_key() -> bytes | None:
        value = os.environ.get("JARVIS_RUN_STATE_KEY")
        return value.encode("utf-8") if value else None

    def _persist_role_tasks(self) -> None:
        """Save active role task records before shutdown."""
        records = self.role_tasks.list(limit=100)
        self.role_task_repo.save(list(records))

    def shutdown(self) -> None:
        with self._shutdown_lock:
            first_error = None
            for resource, cleanup in (
                ("role_tasks_persist", self._persist_role_tasks),
                ("role_tasks", self.role_tasks.shutdown),
                ("orchestrator", self.orchestrator.shutdown),
                ("agent_factory", self.agent_factory.shutdown),
                ("terminal", self.terminal.close),
                ("plugin_manager", self.plugin_manager.close),
                ("event_bus", self.event_bus.destroy),
            ):
                if resource in self._shutdown_completed:
                    continue
                try:
                    cleanup()
                except Exception as error:
                    if first_error is None:
                        first_error = error
                else:
                    self._shutdown_completed.add(resource)
            if first_error is not None:
                raise first_error


_active_state: ContextVar[Optional[AppState]] = ContextVar(
    "jarvis_fastapi_state",
    default=None,
)


class _StateProxy:
    def __init__(self, default_state: AppState):
        object.__setattr__(self, "_default_state", default_state)

    def _target(self) -> AppState:
        return _active_state.get() or self._default_state

    def __getattr__(self, name):
        return getattr(self._target(), name)

    def __setattr__(self, name, value):
        setattr(self._target(), name, value)


class _StateBindingMiddleware:
    def __init__(self, asgi_app):
        self.asgi_app = asgi_app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in {"http", "websocket"}:
            await self.asgi_app(scope, receive, send)
            return
        app_state = scope["app"].state.jarvis_state
        token = _active_state.set(app_state)
        try:
            await self.asgi_app(scope, receive, send)
        finally:
            _active_state.reset(token)


_default_state = AppState()
state = _StateProxy(_default_state)
atexit.register(_default_state.shutdown)
app.state.jarvis_state = _default_state
app.add_middleware(_StateBindingMiddleware)

# ============================================================
# Pydantic models
# ============================================================

class ChatRequest(BaseModel):
    model: str = "default"
    messages: list = []
    stream: bool = False

class TerminalRequest(BaseModel):
    command: str
    args: list = []
    timeout: int = 30

class MemoryRequest(BaseModel):
    type: str = "user"
    title: str = ""
    content: str = ""
    tags: list = []
    probe_cleanup_token: Optional[str] = None

class ProbeCleanupRequest(BaseModel):
    cleanup_token: str

class PluginLoadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plugin_id: str

class RoleDispatchRequest(BaseModel):
    role_name: str
    prompt: str
    timeout: int = 300

class CapabilityDispatchRequest(BaseModel):
    capability: str
    prompt: str
    timeout: int = 300

class BatchDispatchRequest(BaseModel):
    tasks: list = []

# ============================================================
# API endpoints - Health & System
# ============================================================

@app.get("/api/health")
async def health():
    """Health check"""
    uptime = time.time() - state.start_time
    return {
        "status": "healthy",
        "uptime": round(uptime, 2),
        "requests": state.request_count,
        "version": "1.1.0",
    }

@app.get("/api/system/stats")
async def system_stats():
    """System statistics"""
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        return {
            "cpu": {
                "usage": cpu,
                "cores": psutil.cpu_count(),
                "model": "Unknown",
            },
            "memory": {
                "total": mem.total,
                "used": mem.used,
                "free": mem.free,
                "usage": mem.percent,
            },
            "disk": {
                "total": disk.total,
                "used": disk.used,
                "free": disk.free,
                "usage": disk.percent,
            },
            "network": {
                "interfaces": [
                    {"name": iface, "ip": addr.address, "status": "up"}
                    for iface, addrs in psutil.net_if_addrs().items()
                    for addr in addrs if addr.family == 2
                ],
            },
        }
    except ImportError:
        return {
            "cpu": {"usage": 0, "cores": 0, "model": "N/A"},
            "memory": {"total": 0, "used": 0, "free": 0, "usage": 0},
            "disk": {"total": 0, "used": 0, "free": 0, "usage": 0},
            "network": {"interfaces": []},
        }

# ============================================================
# API endpoints - Ollama
# ============================================================

@app.get("/api/ollama/status")
async def ollama_status():
    """Ollama status"""
    status = state.ollama.get_status()
    return state.ollama.to_dict(status)

@app.get("/api/ollama/models")
async def ollama_models():
    """Installed models"""
    models = state.ollama.list_models()
    return {"models": [asdict(m) for m in models]}

@app.post("/api/ollama/chat")
async def ollama_chat(request: ChatRequest):
    """Chat request (non-streaming)"""
    if request.stream is not False:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "INVALID_REQUEST",
                "message": "Use /api/ollama/chat/stream for streaming requests",
            },
        )
    result = state.ollama.chat(request.model, request.messages, False)
    if "error" in result:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "OLLAMA_UPSTREAM_ERROR",
                "message": "Ollama chat request failed",
            },
        )
    return result

@app.get("/api/ollama/token-usage")
async def ollama_token_usage():
    """Ollama token usage snapshot"""
    return state.ollama.get_token_usage_snapshot()

def _ollama_chat_stream_response(model: str, messages_list: list):
    """Build one canonical Ollama SSE response."""
    async def generate():
        completed = False
        try:
            for chunk_text, is_done in state.ollama.stream_chat_generator(model, messages_list):
                event_data = json.dumps({
                    "model": model,
                    "content": chunk_text,
                    "done": is_done,
                }, ensure_ascii=False)
                yield f"data: {event_data}\n\n"
                if is_done:
                    completed = True
                    break
            if completed:
                yield "data: [DONE]\n\n"
        except Exception as error:
            error_data = json.dumps({
                "error": {
                    "code": "OLLAMA_STREAM_ERROR",
                    "message": str(error),
                },
            }, ensure_ascii=False)
            yield f"data: {error_data}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@app.get("/api/ollama/chat/stream")
async def ollama_chat_stream(model: str = "default", messages: str = "[]"):
    """Streaming chat (SSE) with query parameters for EventSource clients."""
    try:
        messages_list = json.loads(messages)
    except json.JSONDecodeError:
        messages_list = [{"role": "user", "content": messages}]
    return _ollama_chat_stream_response(model, messages_list)


@app.post("/api/ollama/chat/stream")
async def ollama_chat_stream_post(request: ChatRequest):
    """Streaming chat (SSE) with a JSON body for fetch clients."""
    return _ollama_chat_stream_response(request.model, request.messages)

# ============================================================
# API endpoints - Terminal
# ============================================================

@app.post("/api/terminal/execute")
async def terminal_execute(
    request: TerminalRequest,
    x_jarvis_terminal_token: Optional[str] = Header(default=None),
):
    """Terminal command execution"""
    if not request.command:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "MISSING_COMMAND",
                "message": "Missing command parameter",
            },
        )

    try:
        command, args, timeout = validate_terminal_operation(
            request.command,
            request.args,
            request.timeout,
        )
    except TerminalPolicyError as error:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_TERMINAL_REQUEST", "message": str(error)},
        ) from error
    if not terminal_access_enabled():
        raise HTTPException(
            status_code=403,
            detail={"code": "TERMINAL_DISABLED", "message": "Terminal execution is disabled"},
        )
    if not terminal_request_is_authorized(x_jarvis_terminal_token):
        raise HTTPException(
            status_code=401,
            detail={
                "code": "TERMINAL_UNAUTHORIZED",
                "message": "Terminal capability token is invalid",
            },
        )

    cmd = TerminalCommand(
        id=f"api-{uuid.uuid4().hex[:8]}",
        command=command,
        args=args,
        timeout=timeout,
        risk_level=state.terminal._assess_risk(command),
    )
    result = state.terminal.execute(cmd)
    return result.to_dict()

# ============================================================
# API endpoints - Plugins
# ============================================================

@app.get("/api/plugins")
async def plugins_list():
    """Plugin list"""
    plugins = state.plugin_manager.get_all_plugins()
    return {
        "plugins": [
            {
                "id": p.manifest.plugin_id,
                "name": p.manifest.name,
                "version": p.manifest.version,
                "status": p.status.value,
                "permissions": p.manifest.permissions,
            }
            for p in plugins
        ]
    }


@app.get("/api/capabilities/registry")
async def capabilities_registry(request: Request):
    """Return a bounded, read-only view of repository capabilities."""
    try:
        query = parse_capability_query_items(request.query_params.multi_items())
    except CapabilityRegistryRequestError as error:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "INVALID_REQUEST",
                "message": "Capability registry query is invalid",
            },
        ) from error

    registry = state.capability_registry
    resolver = state.capability_resolver
    target = state.capability_target
    try:
        return await asyncio.to_thread(
            resolve_capability_registry,
            registry,
            resolver,
            target,
            query,
        )
    except Exception as error:
        logger.exception("Capability registry resolution failed")
        raise HTTPException(
            status_code=503,
            detail={
                "code": "CAPABILITY_REGISTRY_UNAVAILABLE",
                "message": "Capability registry is unavailable",
            },
        ) from error

@app.post("/api/plugins/load")
async def plugin_load(request: PluginLoadRequest):
    """Load plugin"""
    if not request.plugin_id.strip():
        raise HTTPException(
            status_code=400,
            detail={
                "code": "MISSING_PLUGIN_ID",
                "message": "Missing plugin_id parameter",
            },
        )
    manifests = state.plugin_manager.discover()
    manifest = next((m for m in manifests if m.plugin_id == request.plugin_id), None)
    if not manifest:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "PLUGIN_NOT_FOUND",
                "message": f"Plugin {request.plugin_id} not found",
            },
        )
    instance = state.plugin_manager.load(manifest)
    return {
        "plugin_id": instance.manifest.plugin_id,
        "name": instance.manifest.name,
        "status": instance.status.value,
    }

@app.post("/api/plugins/enable")
async def plugin_enable(request: PluginLoadRequest):
    """Enable plugin"""
    result = state.plugin_manager.enable(request.plugin_id)
    return {"success": result, "plugin_id": request.plugin_id}

@app.post("/api/plugins/disable")
async def plugin_disable(request: PluginLoadRequest):
    """Disable plugin"""
    result = state.plugin_manager.disable(request.plugin_id)
    return {"success": result, "plugin_id": request.plugin_id}

# ============================================================
# API endpoints - Memory
# ============================================================

@app.get("/api/memory/entries")
async def memory_entries(memory_type: Optional[str] = None):
    """Memory list"""
    mtype = None
    if memory_type:
        try:
            mtype = MemoryType(memory_type)
        except ValueError:
            pass
    entries = state.memory_store.load(mtype)
    return {
        "entries": [
            {
                "id": e.id,
                "type": e.type.value,
                "title": e.title,
                "content": e.content[:200],
                "created_at": e.created_at,
                "tags": e.tags,
                "access_count": e.access_count,
            }
            for e in entries
        ]
    }

@app.post("/api/memory/store")
async def memory_store(request: MemoryRequest):
    """Store memory"""
    try:
        mtype = MemoryType(request.type)
    except ValueError:
        mtype = MemoryType.USER
    metadata = {}
    if request.probe_cleanup_token:
        metadata["probe_cleanup_token"] = request.probe_cleanup_token
    entry = MemoryEntry.create(
        mtype,
        request.title,
        request.content,
        metadata=metadata,
        tags=request.tags,
    )
    path = state.memory_store.store(entry)
    return {
        "success": True,
        "path": path,
        "id": entry.id,
        "type": entry.type.value,
    }

@app.delete("/api/memory/probes/{memory_type}/{entry_id}")
async def memory_probe_delete(
    memory_type: MemoryType,
    entry_id: str,
    request: ProbeCleanupRequest,
):
    """Delete one integration probe after cleanup-token verification."""
    if not state.memory_store.delete_probe(
        memory_type,
        entry_id,
        request.cleanup_token,
    ):
        raise HTTPException(
            status_code=404,
            detail={
                "code": "MEMORY_NOT_FOUND",
                "message": "Memory entry not found",
            },
        )
    return {"success": True, "id": entry_id}

# ============================================================
# API endpoints - Events
# ============================================================

@app.get("/api/events")
async def events(limit: int = 100):
    """Event history (event_bus integration)"""
    history = state.event_bus.get_history(limit=limit)
    return {
        "events": [
            {
                "type": str(e.type) if hasattr(e, "type") else str(e),
                "payload": str(getattr(e, "payload", ""))[:200],
                "timestamp": getattr(e, "timestamp", ""),
                "source": getattr(e, "source", ""),
            }
            for e in history
        ]
    }

# ============================================================
# API endpoints - Orchestrator
# ============================================================

@app.get("/api/orchestrator/agents")
async def orchestrator_agents():
    """Return registered agent list"""
    agents = state.orchestrator.list_agents()
    return {"agents": [a.to_dict() for a in agents], "count": len(agents)}

@app.get("/api/orchestrator/history")
async def orchestrator_history(limit: int = 10):
    """Return task history"""
    history = state.orchestrator.collect(limit=max(1, min(100, limit)))
    return {"results": [r.to_dict() for r in history], "count": len(history)}

@app.post("/api/orchestrator/dispatch")
async def orchestrator_dispatch(request: Request):
    """Dispatch task to agent"""
    try:
        data = await request.json()
    except (ValueError, RecursionError) as error:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "INVALID_JSON",
                "message": "Request body must be valid JSON",
            },
        ) from error
    except Exception as error:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "INVALID_REQUEST",
                "message": "Request body must be valid JSON",
            },
        ) from error

    if not isinstance(data, dict):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "INVALID_REQUEST",
                "message": "Request body must be a JSON object",
            },
        )

    agent_name = _normalize_dispatch_text(data.get("agent_name", ""))
    prompt = _normalize_dispatch_text(data.get("prompt", ""))
    timeout = data.get("timeout", 300)
    priority = data.get("priority", 1)

    if (
        agent_name is None
        or prompt is None
    ):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "INVALID_REQUEST",
                "message": "agent_name and prompt are required",
            },
        )

    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, int)
        or not 1 <= timeout <= 300
    ):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "INVALID_REQUEST",
                "message": "timeout must be an integer between 1 and 300",
            },
        )
    if (
        isinstance(priority, bool)
        or not isinstance(priority, int)
        or priority < 0
        or priority > 3
    ):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "INVALID_REQUEST",
                "message": "priority must be an integer between 0 and 3",
            },
        )

    task = AgentTask(
        task_id=f"api-{uuid.uuid4().hex[:8]}",
        agent_name=agent_name,
        prompt=prompt,
        timeout=timeout,
        priority=priority,
        metadata={"source": "api"},
    )
    result = state.orchestrator.dispatch(task)
    return result.to_dict()

# ============================================================
# API endpoints - Phase 11 Role-driven dispatch (Iteration #24)
# ============================================================

@app.get("/api/roles")
async def list_roles(capability: Optional[str] = None):
    """List all registered roles, optionally filtered by capability"""
    if capability is not None and not capability.strip():
        capability = None
    roles = state.role_registry.list_roles(capability=capability)
    return {
        "roles": [r.to_dict() for r in roles],
        "count": len(roles),
    }

async def _read_role_body(request: Request) -> dict:
    try:
        data = await request.json()
    except (ValueError, RecursionError) as error:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "INVALID_JSON",
                "message": "Request body must be valid JSON",
            },
        ) from error
    except Exception as error:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "INVALID_REQUEST",
                "message": "Request body must be valid JSON",
            },
        ) from error
    if not isinstance(data, dict):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "INVALID_REQUEST",
                "message": "Request body must be a JSON object",
            },
        )
    return data


def _validate_role_timeout(timeout: object) -> int:
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, int)
        or not 1 <= timeout <= 300
    ):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "INVALID_REQUEST",
                "message": "timeout must be an integer between 1 and 300",
            },
        )
    return timeout


def _role_dispatch_http_error(code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={"code": code, "message": message},
    )


@app.post("/api/roles/tasks", status_code=202)
async def create_role_task(request: Request):
    data = await _read_role_body(request)
    if set(data) - {"role_name", "prompt", "timeout"}:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "INVALID_REQUEST",
                "message": "Request body contains unsupported fields",
            },
        )
    role_name = _normalize_dispatch_text(data.get("role_name", ""))
    prompt = _normalize_dispatch_text(data.get("prompt", ""))
    if role_name is None:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "INVALID_REQUEST",
                "message": "role_name must be a non-empty string",
            },
        )
    if prompt is None:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "INVALID_REQUEST",
                "message": "prompt must be a non-empty string",
            },
        )
    timeout = _validate_role_timeout(data.get("timeout", 300))
    if state.role_registry.get(role_name) is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "ROLE_NOT_FOUND",
                "message": f"Role '{role_name}' not found",
            },
        )
    worker_request = WorkerTaskRequest.new(
        role_name,
        prompt,
        timeout,
        task_id=f"task-{uuid.uuid4().hex}",
    )
    try:
        record = await asyncio.to_thread(state.role_tasks.submit, worker_request)
    except (OSError, RuntimeError) as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "ROLE_WORKER_UNAVAILABLE",
                "message": "Role worker is unavailable",
            },
        ) from exc
    return record.to_dict()


@app.get("/api/roles/tasks")
async def list_role_tasks(limit: int = Query(default=100, ge=1, le=100)):
    records = state.role_tasks.list(limit=limit)
    return {
        "tasks": [record.to_dict() for record in records],
        "count": len(records),
    }


@app.get("/api/roles/tasks/{task_id}")
async def get_role_task(task_id: str):
    record = state.role_tasks.get(task_id)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "ROLE_TASK_NOT_FOUND",
                "message": "Role task was not found",
            },
        )
    return record.to_dict()


@app.post("/api/roles/tasks/{task_id}/cancel")
async def cancel_role_task(task_id: str):
    try:
        record = await asyncio.to_thread(state.role_tasks.cancel, task_id)
    except WorkerTaskTerminalError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "ROLE_TASK_TERMINAL",
                "message": "Role task is already terminal",
            },
        ) from exc
    if record is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "ROLE_TASK_NOT_FOUND",
                "message": "Role task was not found",
            },
        )
    if record.status.is_terminal and record.status is not WorkerTaskStatus.CANCELLED:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "ROLE_TASK_TERMINAL",
                "message": "Role task is already terminal",
            },
        )
    if record.status is not WorkerTaskStatus.CANCELLED:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "ROLE_TASK_TERMINATION_UNCONFIRMED",
                "message": "Worker process termination is not confirmed",
            },
        )
    return record.to_dict()


@app.get("/api/roles/{role_name}")
async def get_role(role_name: str):
    """Get specific role details"""
    profile = state.role_registry.get(role_name)
    if not profile:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "ROLE_NOT_FOUND",
                "message": f"Role '{role_name}' not found",
            },
        )
    return {"role": profile.to_dict()}


@app.post("/api/roles/dispatch")
async def dispatch_by_role(request: Request):
    """Dispatch task to a specific role"""
    data = await _read_role_body(request)
    role_name = _normalize_dispatch_text(data.get("role_name", ""))
    prompt = _normalize_dispatch_text(data.get("prompt", ""))
    if role_name is None:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "INVALID_REQUEST",
                "message": "role_name must be a non-empty string",
            },
        )
    if prompt is None:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "INVALID_REQUEST",
                "message": "prompt must be a non-empty string",
            },
        )
    timeout = _validate_role_timeout(data.get("timeout", 300))
    try:
        result = await asyncio.to_thread(
            state.role_dispatch.dispatch_by_role,
            role_name,
            prompt,
            timeout,
        )
    except RoleWorkerUnavailableError:
        raise _role_dispatch_http_error(
            "ROLE_WORKER_UNAVAILABLE",
            "Role worker is unavailable",
        ) from None
    except RoleTaskTerminationUnconfirmedError:
        raise _role_dispatch_http_error(
            "ROLE_TASK_TERMINATION_UNCONFIRMED",
            "Worker process termination is not confirmed",
        ) from None
    except RoleWorkerInvalidResultError:
        raise _role_dispatch_http_error(
            "ROLE_WORKER_INVALID_RESULT",
            "Role worker returned an invalid result",
        ) from None
    if result.status == "no_role":
        raise HTTPException(
            status_code=404,
            detail={
                "code": "ROLE_NOT_FOUND",
                "message": f"Role '{role_name}' not found",
            },
        )
    return result.to_dict()

@app.post("/api/roles/dispatch_by_cap")
async def dispatch_by_capability(request: Request):
    """Dispatch task by capability (auto-selects highest priority role)"""
    data = await _read_role_body(request)
    capability = _normalize_dispatch_text(data.get("capability", ""))
    prompt = _normalize_dispatch_text(data.get("prompt", ""))
    if capability is None:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "INVALID_REQUEST",
                "message": "capability must be a non-empty string",
            },
        )
    if prompt is None:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "INVALID_REQUEST",
                "message": "prompt must be a non-empty string",
            },
        )
    timeout = _validate_role_timeout(data.get("timeout", 300))
    try:
        result = await asyncio.to_thread(
            state.role_dispatch.dispatch_by_capability,
            capability,
            prompt,
            timeout,
        )
    except RoleWorkerUnavailableError:
        raise _role_dispatch_http_error(
            "ROLE_WORKER_UNAVAILABLE",
            "Role worker is unavailable",
        ) from None
    except RoleTaskTerminationUnconfirmedError:
        raise _role_dispatch_http_error(
            "ROLE_TASK_TERMINATION_UNCONFIRMED",
            "Worker process termination is not confirmed",
        ) from None
    except RoleWorkerInvalidResultError:
        raise _role_dispatch_http_error(
            "ROLE_WORKER_INVALID_RESULT",
            "Role worker returned an invalid result",
        ) from None
    if result.status == "no_capability":
        raise HTTPException(
            status_code=404,
            detail={
                "code": "CAPABILITY_NOT_FOUND",
                "message": f"No role with capability: {capability}",
            },
        )
    return result.to_dict()

@app.post("/api/roles/batch_dispatch")
async def batch_dispatch(request: Request):
    """Batch dispatch multiple tasks"""
    data = await _read_role_body(request)
    tasks = data.get("tasks", [])
    if not isinstance(tasks, list):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "INVALID_REQUEST",
                "message": "tasks must be an array",
            },
        )
    results = await asyncio.to_thread(
        state.role_dispatch.batch_dispatch,
        tasks,
    )
    return {"results": [r.to_dict() for r in results], "count": len(results)}


def create_app(app_state: Optional[AppState] = None) -> FastAPI:
    """Create an isolated FastAPI application with its own lifecycle state."""
    application = FastAPI(
        title="J.A.R.V.I.S. API",
        description="XiaoYi autonomous evolution engine - REST API",
        version="1.1.0",
        lifespan=lifespan,
    )
    application.add_middleware(_RequestBodyLimitMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=configured_allowed_origins(),
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-Jarvis-Terminal-Token"],
    )
    application.add_middleware(_StateBindingMiddleware)
    application.add_exception_handler(HTTPException, http_exception_handler)
    application.add_exception_handler(
        RequestValidationError,
        request_validation_exception_handler,
    )
    standard_paths = {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}
    for route in app.router.routes:
        if getattr(route, "path", None) not in standard_paths:
            application.router.routes.append(route)
    application.state.jarvis_state = app_state or AppState()
    return application

# ============================================================
# Direct execution
# ============================================================



if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=os.environ.get("JARVIS_HOST", "127.0.0.1"), port=8080)
