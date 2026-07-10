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

import json
import logging
import os
import sys
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from core.brain.agent_factory import AgentFactory
from core.brain.context_compressor import MemoryEntry, MemoryStore, MemoryType
from core.brain.orchestrator import AgentTask, Orchestrator
from core.brain.role_registry import create_default_registry

# Phase 11 imports (moved to top to resolve E402)
from core.kernel.ollama_manager import OllamaManager
from core.kernel.plugin_sdk import global_plugin_manager
from core.kernel.terminal_executor import TerminalCommand, TerminalExecutor

# Add src to path (after imports so Phase 11 modules resolve)
sys_path = str(Path(__file__).parent)
if sys_path not in sys.path:
    sys.path.insert(0, sys_path)

logger = logging.getLogger(__name__)


def configured_allowed_origins() -> list[str]:
    raw = os.environ.get("JARVIS_ALLOWED_ORIGINS", "*")
    return [origin.strip() for origin in raw.split(",") if origin.strip()]

# ============================================================
# FastAPI app initialization
# ============================================================

app = FastAPI(
    title="J.A.R.V.I.S. API",
    description="XiaoYi autonomous evolution engine - REST API",
    version="1.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=configured_allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
# Global state
# ============================================================

class AppState:
    """Application global state"""
    def __init__(self):
        self.ollama = OllamaManager()
        self.terminal = TerminalExecutor()
        self.memory_store = MemoryStore(memory_dir=".auto-memory")
        self.orchestrator = Orchestrator()
        self.role_registry = create_default_registry()
        self.agent_factory = AgentFactory(
            registry=self.role_registry,
            orchestrator=self.orchestrator,
        )
        self.start_time = time.time()
        self.request_count = 0

state = AppState()

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

class PluginLoadRequest(BaseModel):
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
    result = state.ollama.chat(request.model, request.messages, request.stream)
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    usage = result.get("usage")
    if isinstance(usage, dict):
        state.ollama.record_token_usage(
            prompt_tokens=int(usage.get("prompt_tokens", 0) or 0),
            completion_tokens=int(usage.get("completion_tokens", 0) or 0),
        )
    else:
        state.ollama.record_token_usage()
    return result

@app.get("/api/ollama/token-usage")
async def ollama_token_usage():
    """Ollama token usage snapshot"""
    usage = state.ollama.get_token_usage()
    return usage.to_dict()

@app.get("/api/ollama/chat/stream")
async def ollama_chat_stream(model: str = "default", messages: str = "[]"):
    """Streaming chat (SSE)"""
    try:
        messages_list = json.loads(messages)
    except json.JSONDecodeError:
        messages_list = [{"role": "user", "content": messages}]

    async def generate():
        try:
            for chunk_text, is_done in state.ollama.stream_chat_generator(model, messages_list):
                event_data = json.dumps({
                    "model": model,
                    "content": chunk_text,
                    "done": is_done,
                }, ensure_ascii=False)
                yield f"data: {event_data}\n\n"
                if is_done:
                    break
            yield "data: [DONE]\n\n"
        except Exception as e:
            error_data = json.dumps({"error": str(e)}, ensure_ascii=False)
            yield f"data: {error_data}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )

# ============================================================
# API endpoints - Terminal
# ============================================================

@app.post("/api/terminal/execute")
async def terminal_execute(request: TerminalRequest):
    """Terminal command execution"""
    if not request.command:
        raise HTTPException(status_code=400, detail="Missing command parameter")

    cmd = TerminalCommand(
        id=f"api-{uuid.uuid4().hex[:8]}",
        command=request.command,
        args=request.args,
        timeout=request.timeout,
        risk_level=state.terminal._assess_risk(request.command),
    )
    result = state.terminal.execute(cmd)
    return result.to_dict()

# ============================================================
# API endpoints - Plugins
# ============================================================

@app.get("/api/plugins")
async def plugins_list():
    """Plugin list"""
    plugins = global_plugin_manager.get_all_plugins()
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

@app.post("/api/plugins/load")
async def plugin_load(request: PluginLoadRequest):
    """Load plugin"""
    manifests = global_plugin_manager.discover()
    manifest = next((m for m in manifests if m.plugin_id == request.plugin_id), None)
    if not manifest:
        raise HTTPException(status_code=404, detail=f"Plugin {request.plugin_id} not found")
    instance = global_plugin_manager.load(manifest)
    return {
        "plugin_id": instance.manifest.plugin_id,
        "name": instance.manifest.name,
        "status": instance.status.value,
    }

@app.post("/api/plugins/enable")
async def plugin_enable(request: PluginLoadRequest):
    """Enable plugin"""
    result = global_plugin_manager.enable(request.plugin_id)
    return {"success": result, "plugin_id": request.plugin_id}

@app.post("/api/plugins/disable")
async def plugin_disable(request: PluginLoadRequest):
    """Disable plugin"""
    result = global_plugin_manager.disable(request.plugin_id)
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
    entry = MemoryEntry.create(mtype, request.title, request.content, tags=request.tags)
    path = state.memory_store.store(entry)
    return {"success": True, "path": path}

# ============================================================
# API endpoints - Events
# ============================================================

@app.get("/api/events")
async def events(limit: int = 100):
    """Event history (event_bus integration)"""
    try:
        from core.kernel.event_bus import global_event_bus
        history = global_event_bus.get_history(limit=limit)
    except (ImportError, AttributeError):
        history = []
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
    history = state.orchestrator.collect(limit=limit)
    return {"results": [r.to_dict() for r in history], "count": len(history)}

@app.post("/api/orchestrator/dispatch")
async def orchestrator_dispatch(request: Request):
    """Dispatch task to agent"""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    agent_name = data.get("agent_name", "")
    prompt = data.get("prompt", "")
    timeout = data.get("timeout", 300)
    priority = data.get("priority", 1)

    if not agent_name or not prompt:
        raise HTTPException(status_code=400, detail="agent_name and prompt are required")

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
    roles = state.role_registry.list_roles(capability=capability)
    return {
        "roles": [r.to_dict() for r in roles],
        "count": len(roles),
    }

@app.get("/api/roles/{role_name}")
async def get_role(role_name: str):
    """Get specific role details"""
    profile = state.role_registry.get(role_name)
    if not profile:
        raise HTTPException(status_code=404, detail=f"Role {role_name} not found")
    return {"role": profile.to_dict()}

@app.post("/api/roles/dispatch")
async def dispatch_by_role(request: RoleDispatchRequest):
    """Dispatch task to a specific role"""
    result = state.agent_factory.dispatch_by_role(
        request.role_name, request.prompt, timeout=request.timeout
    )
    return result.to_dict()

@app.post("/api/roles/dispatch_by_cap")
async def dispatch_by_capability(request: CapabilityDispatchRequest):
    """Dispatch task by capability (auto-selects highest priority role)"""
    result = state.agent_factory.dispatch_by_capability(
        request.capability, request.prompt, timeout=request.timeout
    )
    if result.status == "no_capability":
        raise HTTPException(
            status_code=404,
            detail=f"No role with capability: {request.capability}",
        )
    return result.to_dict()

@app.post("/api/roles/batch_dispatch")
async def batch_dispatch(request: BatchDispatchRequest):
    """Batch dispatch multiple tasks"""
    results = state.agent_factory.batch_dispatch(request.tasks)
    return {"results": [r.to_dict() for r in results], "count": len(results)}

# ============================================================
# Startup / shutdown
# ============================================================

@app.on_event("startup")
async def startup():
    logger.info("J.A.R.V.I.S. FastAPI server started on http://127.0.0.1:8080")

@app.on_event("shutdown")
async def shutdown():
    state.orchestrator.shutdown()
    state.agent_factory.shutdown()
    logger.info("J.A.R.V.I.S. FastAPI server shutdown complete")

# ============================================================
# Direct execution
# ============================================================



if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8080)
