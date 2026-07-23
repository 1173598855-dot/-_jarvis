"""
J.A.R.V.I.S. REST API Server — 小奕核心服务
将所有组件通过 HTTP API 暴露，供前端 Widget 和外部系统调用

运行：python src/main.py
端口：8080

端点：
- GET  /api/health           — 健康检查
- GET  /api/system/stats     — 系统统计
- GET  /api/ollama/status    — Ollama 状态
- GET  /api/ollama/models    — 已安装模型
- POST /api/ollama/chat      — 聊天请求（非流式）
- GET  /api/ollama/chat/stream — 流式聊天（SSE）
- GET  /api/plugins          — 插件列表
- POST /api/plugins/load     — 加载插件
- POST /api/plugins/enable   — 启用插件
- POST /api/plugins/disable  — 禁用插件
- GET  /api/memory/entries   — 记忆列表
- POST /api/memory/store     — 存储记忆
- GET  /api/events           — 事件历史
- GET  /api/orchestrator/agents — 已注册 agent 列表
- GET  /api/orchestrator/history — 任务历史
- POST /api/orchestrator/dispatch — 分发任务
- GET  /api/roles - roles list
- GET  /api/roles/{role_name} - role detail
- POST /api/roles/dispatch - dispatch by role
- POST /api/roles/dispatch_by_cap - dispatch by capability
- POST /api/roles/batch_dispatch - batch dispatch
"""

import atexit
import json
import logging
import os
import socket
import sys
import threading
import time
import uuid
from urllib.parse import parse_qs
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict

# ============================================================
# IPv4-only HTTP Server（解决 Windows WinError 10013）
# ============================================================

class _IPv4HTTPServer(HTTPServer):
    """强制 IPv4 绑定的 HTTP 服务器"""

    def server_bind(self):
        self.socket.close()
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind(self.server_address)
        self.server_address = self.socket.getsockname()

# 添加 src 到路径
sys.path.insert(0, str(Path(__file__).parent))

from core.brain.context_compressor import MemoryEntry, MemoryStore, MemoryType  # noqa: E402
from core.brain.agent_factory import AgentFactory  # noqa: E402
from core.brain.orchestrator import AgentTask, Orchestrator  # noqa: E402
from core.brain.role_dispatch_service import (  # noqa: E402
    RoleDispatchService,
    RoleTaskTerminationUnconfirmedError,
    RoleWorkerInvalidResultError,
    RoleWorkerUnavailableError,
)
from core.brain.role_registry import create_default_registry  # noqa: E402
from core.brain.role_worker import (  # noqa: E402
    RoleWorkerSupervisor,
    apply_worker_token_usage,
    execute_role_task,
)
from core.kernel.ollama_manager import OllamaManager  # noqa: E402
from core.kernel.plugin_sdk import global_plugin_manager  # noqa: E402
from core.kernel.runtime_security import (  # noqa: E402
    configured_allowed_origins,
    terminal_access_enabled,
    terminal_request_is_authorized,
)
from core.kernel.terminal_executor import TerminalCommand, TerminalExecutor  # noqa: E402
from core.kernel.terminal_policy import TerminalPolicyError, validate_terminal_operation  # noqa: E402
from core.kernel.terminal_worker import TerminalWorker  # noqa: E402

logger = logging.getLogger(__name__)
MAX_REQUEST_BODY_BYTES = 32 * 1024
REQUEST_BODY_CHUNK_BYTES = 8 * 1024
REQUEST_BODY_READ_TIMEOUT_SECONDS = 2.0
REQUEST_BODY_DISCARD_TIMEOUT_SECONDS = 0.25


class InvalidJsonBody(ValueError):
    """Raised when an API request body cannot be decoded as JSON."""


class InvalidRequestBody(ValueError):
    """Raised when a valid JSON payload does not match the API request shape."""


class RequestBodyTooLarge(ValueError):
    """Raised when an API request exceeds the shared body-size limit."""


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


def _configured_allowed_origins() -> list[str]:
    return configured_allowed_origins()


# ============================================================
# 全局状态
# ============================================================

class AppState:
    """应用全局状态"""
    def __init__(
        self,
        terminal=None,
        role_tasks: RoleWorkerSupervisor | None = None,
        role_dispatch: RoleDispatchService | None = None,
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
        self.memory_store = MemoryStore(memory_dir=".auto-memory")
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
        self.start_time = time.time()
        self.request_count = 0
        self._lock = threading.Lock()
        self._shutdown_lock = threading.Lock()
        self._shutdown_completed: set[str] = set()

    def increment_requests(self):
        with self._lock:
            self.request_count += 1

    def shutdown(self) -> None:
        with self._shutdown_lock:
            first_error = None
            for resource, cleanup in (
                ("role_tasks", self.role_tasks.shutdown),
                ("orchestrator", self.orchestrator.shutdown),
                ("agent_factory", self.agent_factory.shutdown),
                ("terminal", self.terminal.close),
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


state = AppState()
atexit.register(state.shutdown)


# ============================================================
# HTTP 请求处理器
# ============================================================

class JARVISHandler(BaseHTTPRequestHandler):
    app_state = state

    """J.A.R.V.I.S. API 请求处理器"""

    # 禁用日志（避免控制台噪音）
    def log_message(self, format, *args):
        pass

    def _send_json(self, data: Dict[str, Any], status: int = 200):
        """发送 JSON 响应"""
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._send_cors_headers()
        self.send_header("Content-Length", str(len(body)))
        if self.close_connection:
            self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def _send_error(
        self,
        message: str,
        status: int = 400,
        code: str | None = None,
    ):
        """发送错误响应"""
        self._send_json({
            "error": {
                "code": code or f"HTTP_{status}",
                "message": message,
            }
        }, status)

    def _read_body(self) -> Dict[str, Any]:
        """读取 JSON 请求体"""
        try:
            content_length = int(self.headers.get("Content-Length", 0))
        except (TypeError, ValueError) as error:
            raise InvalidJsonBody("Request body must be valid JSON") from error
        if content_length < 0:
            raise InvalidJsonBody("Request body must be valid JSON")
        if content_length > MAX_REQUEST_BODY_BYTES:
            self._discard_request_body(content_length)
            raise RequestBodyTooLarge("Request body exceeds the 32 KiB limit")
        body, complete = self._consume_request_body(
            content_length,
            collect=True,
            timeout_seconds=REQUEST_BODY_READ_TIMEOUT_SECONDS,
        )
        if not complete or body is None:
            raise InvalidJsonBody("Request body must be valid JSON")
        if not body:
            return {}
        try:
            payload = json.loads(body)
        except (ValueError, RecursionError) as error:
            raise InvalidJsonBody("Request body must be valid JSON") from error
        if not isinstance(payload, dict):
            raise InvalidRequestBody("Request body must be a JSON object")
        return payload

    def _consume_request_body(
        self,
        content_length: int,
        *,
        collect: bool,
        timeout_seconds: float,
    ) -> tuple[bytes | None, bool]:
        """Read or discard a declared body under one total socket deadline."""
        remaining = content_length
        deadline = time.monotonic() + timeout_seconds
        chunks = [] if collect else None
        connection = getattr(self, "connection", None)
        original_timeout = None
        restore_timeout = False

        if connection is not None:
            try:
                original_timeout = connection.gettimeout()
                restore_timeout = True
            except (AttributeError, OSError):
                self.close_connection = True
                return None, False

        try:
            while remaining > 0:
                remaining_time = deadline - time.monotonic()
                if remaining_time <= 0:
                    break
                if connection is not None:
                    try:
                        connection.settimeout(remaining_time)
                    except (AttributeError, OSError):
                        break
                read_size = min(remaining, REQUEST_BODY_CHUNK_BYTES)
                try:
                    chunk = self.rfile.read(read_size)
                except (OSError, ValueError):
                    break
                if not chunk:
                    break
                chunk = chunk[:read_size]
                if chunks is not None:
                    chunks.append(chunk)
                remaining -= len(chunk)
        finally:
            if restore_timeout:
                try:
                    getattr(self, "connection").settimeout(original_timeout)
                except (AttributeError, OSError):
                    self.close_connection = True

        complete = remaining == 0
        if not complete:
            self.close_connection = True
        body = b"".join(chunks) if complete and chunks is not None else None
        return body, complete

    def _discard_request_body(self, content_length: int) -> bool:
        """Best-effort bounded discard before returning an oversized-body error."""
        _, complete = self._consume_request_body(
            content_length,
            collect=False,
            timeout_seconds=REQUEST_BODY_DISCARD_TIMEOUT_SECONDS,
        )
        return complete

    def _send_cors_headers(self):
        allowed_origins = _configured_allowed_origins()
        request_origin = self.headers.get("Origin") if self.headers else None

        if "*" in allowed_origins:
            self.send_header("Access-Control-Allow-Origin", "*")
        elif request_origin in allowed_origins:
            self.send_header("Access-Control-Allow-Origin", request_origin)
            self.send_header("Vary", "Origin")

        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type, X-Jarvis-Terminal-Token",
        )

    def _cors(self):
        """处理 CORS 预检请求"""
        if self.command == "OPTIONS":
            self.send_response(204)
            self._send_cors_headers()
            self.end_headers()
            return True
        return False

    # ============================================================
    # 路由处理
    # ============================================================

    def do_GET(self):
        """GET 请求路由"""
        if self._cors():
            return

        self.app_state.increment_requests()
        request_path = self.path.split("?", 1)[0]
        routes = {
            "/api/health": self.handle_health,
            "/api/system/stats": self.handle_system_stats,
            "/api/ollama/status": self.handle_ollama_status,
            "/api/ollama/models": self.handle_ollama_models,
            "/api/ollama/chat/stream": self.handle_ollama_chat_stream,
            "/api/ollama/token-usage": self.handle_ollama_token_usage,
            "/api/plugins": self.handle_plugins_list,
            "/api/memory/entries": self.handle_memory_entries,
            "/api/events": self.handle_events,
            "/api/orchestrator/agents": self.handle_orchestrator_agents,
            "/api/orchestrator/history": self.handle_orchestrator_history,
            "/api/roles": self.handle_roles_list,
        }

        handler = routes.get(request_path)
        if handler:
            handler()
            return

        roles_prefix = "/api/roles/"
        if request_path.startswith(roles_prefix):
            role_name = request_path.removeprefix(roles_prefix)
            if role_name and "/" not in role_name:
                self.handle_role_get(role_name)
                return

        self._send_error(f"Not Found: {self.path}", 404)

    def do_POST(self):
        """POST 请求路由"""
        if self._cors():
            return

        self.app_state.increment_requests()
        routes = {
            "/api/ollama/chat": self.handle_ollama_chat,
            "/api/ollama/chat/stream": self.handle_ollama_chat_stream_post,
            "/api/ollama/token-usage": self.handle_ollama_token_usage,
            "/api/terminal/execute": self.handle_terminal_execute,
            "/api/plugins/load": self.handle_plugin_load,
            "/api/plugins/enable": self.handle_plugin_enable,
            "/api/plugins/disable": self.handle_plugin_disable,
            "/api/memory/store": self.handle_memory_store,
            "/api/orchestrator/dispatch": self.handle_orchestrator_dispatch,
            "/api/roles/dispatch": self.handle_role_dispatch,
            "/api/roles/dispatch_by_cap": self.handle_role_dispatch_by_cap,
            "/api/roles/batch_dispatch": self.handle_role_batch_dispatch,
        }

        handler = routes.get(self.path)
        if handler:
            try:
                handler()
            except InvalidJsonBody as error:
                self._send_error(str(error), 400, "INVALID_JSON")
            except InvalidRequestBody as error:
                self._send_error(str(error), 400, "INVALID_REQUEST")
            except RequestBodyTooLarge as error:
                self._send_error(str(error), 413, "REQUEST_BODY_TOO_LARGE")
        else:
            self._send_error(f"Not Found: {self.path}", 404)

    def do_DELETE(self):
        """DELETE request routing."""
        if self._cors():
            return

        self.app_state.increment_requests()
        prefix = "/api/memory/probes/"
        if self.path.startswith(prefix):
            parts = self.path.removeprefix(prefix).split("/", 1)
            if len(parts) == 2:
                try:
                    memory_type = MemoryType(parts[0])
                except ValueError:
                    pass
                else:
                    try:
                        self.handle_memory_delete(memory_type, parts[1])
                    except InvalidJsonBody as error:
                        self._send_error(str(error), 400, "INVALID_JSON")
                    except InvalidRequestBody as error:
                        self._send_error(str(error), 400, "INVALID_REQUEST")
                    except RequestBodyTooLarge as error:
                        self._send_error(
                            str(error),
                            413,
                            "REQUEST_BODY_TOO_LARGE",
                        )
                    return
        self._send_error(f"Not Found: {self.path}", 404)

    # ============================================================
    # API 端点实现
    # ============================================================

    def handle_health(self):
        """健康检查"""
        uptime = time.time() - self.app_state.start_time
        self._send_json({
            "status": "healthy",
            "uptime": round(uptime, 2),
            "requests": self.app_state.request_count,
            "version": "1.0.0",
        })

    def handle_ollama_chat_stream(self):
        """Ollama 流式聊天（SSE）"""
        query = parse_qs(self.path.partition("?")[2])
        model = query.get("model", ["default"])[0]
        messages_raw = query.get("messages", ["[]"])[0]

        try:
            messages = json.loads(messages_raw)
        except json.JSONDecodeError:
            messages = [{"role": "user", "content": messages_raw}]

        self._stream_ollama_chat(model, messages)

    def handle_ollama_chat_stream_post(self):
        """Ollama JSON-body 流式聊天（SSE）"""
        data = self._read_body()
        self._stream_ollama_chat(
            data.get("model", "default"),
            data.get("messages", []),
        )

    def _stream_ollama_chat(self, model: str, messages: list):
        """Write one canonical Ollama SSE response."""

        # SSE 响应头
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("Connection", "keep-alive")
        self._send_cors_headers()
        self.end_headers()

        completed = False
        try:
            for chunk_text, is_done in self.app_state.ollama.stream_chat_generator(model, messages):
                event_data = json.dumps({
                    "model": model,
                    "content": chunk_text,
                    "done": is_done,
                }, ensure_ascii=False)
                self.wfile.write(f"data: {event_data}\n\n".encode("utf-8"))
                self.wfile.flush()

                if is_done:
                    completed = True
                    break

            if completed:
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()

        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as error:
            error_data = json.dumps({
                "error": {
                    "code": "OLLAMA_STREAM_ERROR",
                    "message": str(error),
                },
            }, ensure_ascii=False)
            self.wfile.write(f"data: {error_data}\n\n".encode("utf-8"))
            self.wfile.flush()

    def handle_system_stats(self):
        """系统统计"""
        try:
            import psutil
            cpu = psutil.cpu_percent(interval=0.1)
            mem = psutil.virtual_memory()
            disk = psutil.disk_usage("/")

            self._send_json({
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
            })
        except ImportError:
            self._send_json({
                "cpu": {"usage": 0, "cores": 0, "model": "N/A"},
                "memory": {"total": 0, "used": 0, "free": 0, "usage": 0},
                "disk": {"total": 0, "used": 0, "free": 0, "usage": 0},
                "network": {"interfaces": []},
            })

    def handle_ollama_status(self):
        """Ollama 状态"""
        status = self.app_state.ollama.get_status()
        self._send_json(self.app_state.ollama.to_dict(status))

    def handle_ollama_models(self):
        """Ollama 已安装模型"""
        models = self.app_state.ollama.list_models()
        self._send_json({"models": [asdict(model) for model in models]})

    def handle_ollama_chat(self):
        """Ollama 非流式聊天"""
        data = self._read_body()
        model = data.get("model", "default")
        messages = data.get("messages", [])
        if data.get("stream", False) is not False:
            self._send_error(
                "Use /api/ollama/chat/stream for streaming requests",
                400,
                "INVALID_REQUEST",
            )
            return

        result = self.app_state.ollama.chat(model, messages, False)
        if "error" in result:
            self._send_error(
                "Ollama chat request failed",
                502,
                "OLLAMA_UPSTREAM_ERROR",
            )
            return
        self._send_json(result)

    def handle_ollama_token_usage(self):
        """Ollama token usage snapshot"""
        self._send_json(self.app_state.ollama.get_token_usage_snapshot())

    def handle_terminal_execute(self):
        """终端命令执行"""
        data = self._read_body()
        command = data.get("command", "")
        args = data.get("args", [])
        timeout = data.get("timeout", 30)

        if not command:
            self._send_error(
                "Missing command parameter",
                code="MISSING_COMMAND",
            )
            return

        try:
            command, args, timeout = validate_terminal_operation(command, args, timeout)
        except TerminalPolicyError as error:
            self._send_error(str(error), 400, "INVALID_TERMINAL_REQUEST")
            return
        if not terminal_access_enabled():
            self._send_error("Terminal execution is disabled", 403, "TERMINAL_DISABLED")
            return
        if not terminal_request_is_authorized(
            self.headers.get("X-Jarvis-Terminal-Token"),
        ):
            self._send_error("Terminal capability token is invalid", 401, "TERMINAL_UNAUTHORIZED")
            return

        cmd = TerminalCommand(
            id=f"api-{uuid.uuid4().hex[:8]}",
            command=command,
            args=args,
            timeout=timeout,
            risk_level=self.app_state.terminal._assess_risk(command),
        )
        result = self.app_state.terminal.execute(cmd)
        self._send_json(result.to_dict())

    def handle_plugins_list(self):
        """插件列表"""
        plugins = global_plugin_manager.get_all_plugins()
        self._send_json({
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
        })

    def handle_plugin_load(self):
        """加载插件"""
        data = self._read_body()
        plugin_id = data.get("plugin_id")
        if not plugin_id:
            self._send_error(
                "Missing plugin_id parameter",
                code="MISSING_PLUGIN_ID",
            )
            return

        # 查找 manifest
        manifests = global_plugin_manager.discover()
        manifest = next((m for m in manifests if m.plugin_id == plugin_id), None)
        if not manifest:
            self._send_error(
                f"Plugin {plugin_id} not found",
                404,
                "PLUGIN_NOT_FOUND",
            )
            return

        instance = global_plugin_manager.load(manifest)
        self._send_json({
            "plugin_id": instance.manifest.plugin_id,
            "name": instance.manifest.name,
            "status": instance.status.value,
        })

    def handle_plugin_enable(self):
        """启用插件"""
        data = self._read_body()
        plugin_id = data.get("plugin_id")
        if not plugin_id:
            self._send_error("Missing plugin_id parameter")
            return

        result = global_plugin_manager.enable(plugin_id)
        self._send_json({"success": result, "plugin_id": plugin_id})

    def handle_plugin_disable(self):
        """禁用插件"""
        data = self._read_body()
        plugin_id = data.get("plugin_id")
        if not plugin_id:
            self._send_error("Missing plugin_id parameter")
            return

        result = global_plugin_manager.disable(plugin_id)
        self._send_json({"success": result, "plugin_id": plugin_id})

    def handle_memory_entries(self):
        """记忆列表"""
        memory_type = self.headers.get("X-Memory-Type")
        mtype = None
        if memory_type:
            try:
                mtype = MemoryType(memory_type)
            except ValueError:
                pass

        entries = self.app_state.memory_store.load(mtype)
        self._send_json({
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
        })

    def handle_memory_store(self):
        """存储记忆"""
        data = self._read_body()
        memory_type = data.get("type", "user")
        title = data.get("title", "")
        content_inner = data.get("content", "")
        tags = data.get("tags", [])
        probe_cleanup_token = data.get("probe_cleanup_token")

        try:
            mtype = MemoryType(memory_type)
        except ValueError:
            mtype = MemoryType.USER

        metadata = {}
        if isinstance(probe_cleanup_token, str) and probe_cleanup_token:
            metadata["probe_cleanup_token"] = probe_cleanup_token
        entry = MemoryEntry.create(
            mtype,
            title,
            content_inner,
            metadata=metadata,
            tags=tags,
        )
        path = self.app_state.memory_store.store(entry)
        self._send_json({
            "success": True,
            "path": path,
            "id": entry.id,
            "type": entry.type.value,
        })

    def handle_memory_delete(self, memory_type: MemoryType, entry_id: str):
        """Delete one integration probe after cleanup-token verification."""
        cleanup_token = self._read_body().get("cleanup_token", "")
        deleted = self.app_state.memory_store.delete_probe(
            memory_type,
            entry_id,
            cleanup_token,
        )
        if not deleted:
            self._send_error("Memory entry not found", 404, "MEMORY_NOT_FOUND")
            return
        self._send_json({"success": True, "id": entry_id})

    def handle_events(self):
        """Event history (event_bus module removed, returns empty list for now)"""
        self._send_json({"events": []})

    # ============================================================
    # Orchestrator endpoints
    # ============================================================

    def handle_orchestrator_agents(self):
        """List registered agents"""
        try:
            agents = self.app_state.orchestrator.list_agents()
            self._send_json({
                "agents": [a.to_dict() for a in agents],
                "count": len(agents),
            })
        except Exception as e:
            self._send_error(f"Failed to list agents: {e}", 500)

    def handle_orchestrator_history(self):
        """Task execution history"""
        query_limit = parse_qs(
            self.path.partition("?")[2],
            keep_blank_values=True,
        ).get("limit", [None])[0]
        raw_limit = query_limit
        if raw_limit is None:
            raw_limit = self.headers.get("X-Limit", 10)

        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            self._send_error(
                "limit must be an integer",
                400,
                "INVALID_REQUEST",
            )
            return

        limit = max(1, min(limit, 100))
        try:
            history = self.app_state.orchestrator.collect(limit=limit)
            self._send_json({
                "results": [r.to_dict() for r in history],
                "count": len(history),
            })
        except Exception as e:
            self._send_error(f"Failed to collect history: {e}", 500)

    def handle_orchestrator_dispatch(self):
        """Dispatch a task to a registered agent (simulated execution)"""
        data = self._read_body()
        agent_name = _normalize_dispatch_text(data.get("agent_name", ""))
        prompt = _normalize_dispatch_text(data.get("prompt", ""))
        timeout = data.get("timeout", 300)
        priority = data.get("priority", 1)

        if agent_name is None:
            self._send_error(
                "agent_name must be a non-empty string",
                400,
                "INVALID_REQUEST",
            )
            return
        if prompt is None:
            self._send_error(
                "prompt must be a non-empty string",
                400,
                "INVALID_REQUEST",
            )
            return
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, int)
            or not 1 <= timeout <= 300
        ):
            self._send_error(
                "timeout must be an integer between 1 and 300",
                400,
                "INVALID_REQUEST",
            )
            return
        if (
            isinstance(priority, bool)
            or not isinstance(priority, int)
            or not 0 <= priority <= 3
        ):
            self._send_error(
                "priority must be an integer between 0 and 3",
                400,
                "INVALID_REQUEST",
            )
            return

        logger.info(f"Mock dispatch to '{agent_name}': {prompt[:100]}")
        print(f"[ORCH] agent={agent_name} prompt={prompt}")

        result = self.app_state.orchestrator.dispatch(
            AgentTask(
                agent_name=agent_name,
                prompt=prompt,
                timeout=timeout,
                priority=priority,
            )
        )
        self._send_json(result.to_dict())

    # ============================================================
    # Role endpoints (Phase 11 - shared across adapters)
    # ============================================================

    def handle_roles_list(self):
        """List registered roles, optionally filtered by capability."""
        capability = parse_qs(
            self.path.partition("?")[2],
            keep_blank_values=True,
        ).get("capability", [None])[0]
        if capability is not None and not capability.strip():
            capability = None
        try:
            roles = self.app_state.role_registry.list_roles(capability=capability)
            self._send_json({
                "roles": [r.to_dict() for r in roles],
                "count": len(roles),
            })
        except Exception as e:
            self._send_error(f"Failed to list roles: {e}", 500)

    def handle_role_get(self, role_name):
        """Return a single role profile by name."""
        try:
            profile = self.app_state.role_registry.get(role_name)
        except Exception as e:
            self._send_error(f"Failed to get role: {e}", 500)
            return
        if profile is None:
            self._send_error(
                f"Role '{role_name}' not found",
                404,
                "ROLE_NOT_FOUND",
            )
            return
        self._send_json({"role": profile.to_dict()})

    def _read_role_dispatch_prompt(self, data):
        prompt = _normalize_dispatch_text(data.get("prompt", ""))
        if prompt is None:
            self._send_error(
                "prompt must be a non-empty string",
                400,
                "INVALID_REQUEST",
            )
            return None, None
        timeout = data.get("timeout", 300)
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, int)
            or not 1 <= timeout <= 300
        ):
            self._send_error(
                "timeout must be an integer between 1 and 300",
                400,
                "INVALID_REQUEST",
            )
            return None, None
        return prompt, timeout

    def _send_role_dispatch_error(self, error):
        errors = (
            (
                RoleWorkerUnavailableError,
                "ROLE_WORKER_UNAVAILABLE",
                "Role worker is unavailable",
            ),
            (
                RoleTaskTerminationUnconfirmedError,
                "ROLE_TASK_TERMINATION_UNCONFIRMED",
                "Worker process termination is not confirmed",
            ),
            (
                RoleWorkerInvalidResultError,
                "ROLE_WORKER_INVALID_RESULT",
                "Role worker returned an invalid result",
            ),
        )
        for error_type, code, message in errors:
            if isinstance(error, error_type):
                self._send_error(message, 503, code)
                return
        raise error

    def handle_role_dispatch(self):
        """Dispatch a task to a specific role."""
        data = self._read_body()
        role_name = _normalize_dispatch_text(data.get("role_name", ""))
        if role_name is None:
            self._send_error(
                "role_name must be a non-empty string",
                400,
                "INVALID_REQUEST",
            )
            return
        prompt, timeout = self._read_role_dispatch_prompt(data)
        if prompt is None:
            return
        try:
            result = self.app_state.role_dispatch.dispatch_by_role(
                role_name,
                prompt,
                timeout,
            )
        except (
            RoleWorkerUnavailableError,
            RoleTaskTerminationUnconfirmedError,
            RoleWorkerInvalidResultError,
        ) as error:
            self._send_role_dispatch_error(error)
            return
        if result.status == "no_role":
            self._send_error(
                f"Role '{role_name}' not found",
                404,
                "ROLE_NOT_FOUND",
            )
            return
        self._send_json(result.to_dict())

    def handle_role_dispatch_by_cap(self):
        """Dispatch a task by capability, selecting the highest-priority role."""
        data = self._read_body()
        capability = _normalize_dispatch_text(data.get("capability", ""))
        if capability is None:
            self._send_error(
                "capability must be a non-empty string",
                400,
                "INVALID_REQUEST",
            )
            return
        prompt, timeout = self._read_role_dispatch_prompt(data)
        if prompt is None:
            return
        try:
            result = self.app_state.role_dispatch.dispatch_by_capability(
                capability,
                prompt,
                timeout,
            )
        except (
            RoleWorkerUnavailableError,
            RoleTaskTerminationUnconfirmedError,
            RoleWorkerInvalidResultError,
        ) as error:
            self._send_role_dispatch_error(error)
            return
        if result.status == "no_capability":
            self._send_error(
                f"No role with capability: {capability}",
                404,
                "CAPABILITY_NOT_FOUND",
            )
            return
        self._send_json(result.to_dict())

    def handle_role_batch_dispatch(self):
        """Dispatch multiple role/capability tasks in one request."""
        data = self._read_body()
        tasks = data.get("tasks", [])
        if not isinstance(tasks, list):
            self._send_error(
                "tasks must be an array",
                400,
                "INVALID_REQUEST",
            )
            return
        results = self.app_state.role_dispatch.batch_dispatch(tasks)
        self._send_json({
            "results": [r.to_dict() for r in results],
            "count": len(results),
        })


# ============================================================
# Server start
# ============================================================

def create_http_server(
    host: str,
    port: int,
    app_state: AppState | None = None,
):
    handler_type = JARVISHandler
    if app_state is not None:
        handler_type = type(
            "BoundJARVISHandler",
            (JARVISHandler,),
            {"app_state": app_state},
        )
    return _IPv4HTTPServer((host, port), handler_type)


def run_server(
    host: str | None = None,
    port: int = 8080,
    app_state: AppState | None = None,
):
    """Start J.A.R.V.I.S. API server"""
    host = host or os.environ.get("JARVIS_HOST") or "127.0.0.1"
    active_state = app_state or state
    server = create_http_server(host, port, app_state=active_state)
    logger.info(f"J.A.R.V.I.S. API server started: http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("server shutting down...")
    finally:
        try:
            server.shutdown()
        finally:
            try:
                server.server_close()
            finally:
                active_state.shutdown()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    run_server()
