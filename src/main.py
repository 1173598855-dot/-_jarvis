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
"""

import json
import logging
import os
import socket
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict

# ============================================================
# IPv4-only HTTP Server（解决 Windows WinError 10013）
# ============================================================

class _IPv4HTTPServer(HTTPServer):
    """强制 IPv4 绑定的 HTTP 服务器"""

    def server_bind(self):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind(self.server_address)
        self.server_address = self.socket.getsockname()

# 添加 src 到路径
sys.path.insert(0, str(Path(__file__).parent))

from core.brain.context_compressor import MemoryEntry, MemoryStore, MemoryType  # noqa: E402
from core.brain.orchestrator import AgentTask, Orchestrator  # noqa: E402
from core.kernel.ollama_manager import OllamaManager  # noqa: E402
from core.kernel.plugin_sdk import global_plugin_manager  # noqa: E402
from core.kernel.terminal_executor import TerminalCommand, TerminalExecutor  # noqa: E402

logger = logging.getLogger(__name__)


def _configured_allowed_origins() -> list[str]:
    raw = os.environ.get("JARVIS_ALLOWED_ORIGINS", "*")
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


# ============================================================
# 全局状态
# ============================================================

class AppState:
    """应用全局状态"""
    def __init__(self):
        self.ollama = OllamaManager()
        self.terminal = TerminalExecutor()
        self.memory_store = MemoryStore(memory_dir=".auto-memory")
        self.orchestrator = Orchestrator()
        self.start_time = time.time()
        self.request_count = 0
        self._lock = threading.Lock()

    def increment_requests(self):
        with self._lock:
            self.request_count += 1


state = AppState()


# ============================================================
# HTTP 请求处理器
# ============================================================

class JARVISHandler(BaseHTTPRequestHandler):
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
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, message: str, status: int = 400):
        """发送错误响应"""
        self._send_json({"error": message}, status)

    def _read_body(self) -> Dict[str, Any]:
        """读取 JSON 请求体"""
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            return json.loads(body) if body else {}
        except Exception:
            return {}

    def _send_cors_headers(self):
        allowed_origins = _configured_allowed_origins()
        request_origin = self.headers.get("Origin") if self.headers else None

        if "*" in allowed_origins:
            self.send_header("Access-Control-Allow-Origin", "*")
        elif request_origin in allowed_origins:
            self.send_header("Access-Control-Allow-Origin", request_origin)
            self.send_header("Vary", "Origin")

        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

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

        state.increment_requests()
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
        }

        handler = routes.get(self.path)
        if handler:
            handler()
        else:
            self._send_error(f"Not Found: {self.path}", 404)

    def do_POST(self):
        """POST 请求路由"""
        if self._cors():
            return

        state.increment_requests()
        routes = {
            "/api/ollama/chat": self.handle_ollama_chat,
            "/api/ollama/token-usage": self.handle_ollama_token_usage,
            "/api/terminal/execute": self.handle_terminal_execute,
            "/api/plugins/load": self.handle_plugin_load,
            "/api/plugins/enable": self.handle_plugin_enable,
            "/api/plugins/disable": self.handle_plugin_disable,
            "/api/memory/store": self.handle_memory_store,
            "/api/orchestrator/dispatch": self.handle_orchestrator_dispatch,
        }

        handler = routes.get(self.path)
        if handler:
            handler()
        else:
            self._send_error(f"Not Found: {self.path}", 404)

    # ============================================================
    # API 端点实现
    # ============================================================

    def handle_health(self):
        """健康检查"""
        uptime = time.time() - state.start_time
        self._send_json({
            "status": "healthy",
            "uptime": round(uptime, 2),
            "requests": state.request_count,
            "version": "1.0.0",
        })

    def handle_ollama_chat_stream(self):
        """Ollama 流式聊天（SSE）"""
        # 从查询参数读取
        query = {}
        if '?' in self.path:
            qs = self.path.split('?', 1)[1]
            for pair in qs.split('&'):
                if '=' in pair:
                    k, v = pair.split('=', 1)
                    query[k] = v

        model = query.get("model", "default")
        messages_raw = query.get("messages", "[]")

        try:
            messages = json.loads(messages_raw)
        except json.JSONDecodeError:
            messages = [{"role": "user", "content": messages_raw}]

        # SSE 响应头
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("Connection", "keep-alive")
        self._send_cors_headers()
        self.end_headers()

        try:
            for chunk_text, is_done in state.ollama.stream_chat_generator(model, messages):
                event_data = json.dumps({
                    "model": model,
                    "content": chunk_text,
                    "done": is_done,
                }, ensure_ascii=False)
                self.wfile.write(f"data: {event_data}\n\n".encode("utf-8"))
                self.wfile.flush()

                if is_done:
                    break

            # 结束事件
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()

        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            error_data = json.dumps({"error": str(e)}, ensure_ascii=False)
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
        status = state.ollama.get_status()
        self._send_json(state.ollama.to_dict(status))

    def handle_ollama_models(self):
        """Ollama 已安装模型"""
        models = state.ollama.list_models()
        self._send_json({"models": [m.to_dict() if hasattr(m, 'to_dict') else m for m in models]})

    def handle_ollama_chat(self):
        """Ollama 聊天"""
        data = self._read_body()
        model = data.get("model", "default")
        messages = data.get("messages", [])
        stream = data.get("stream", False)

        result = state.ollama.chat(model, messages, stream)
        if isinstance(result, dict):
            usage = result.get("usage")
            if isinstance(usage, dict):
                state.ollama.record_token_usage(
                    prompt_tokens=int(usage.get("prompt_tokens", 0) or 0),
                    completion_tokens=int(usage.get("completion_tokens", 0) or 0),
                )
            else:
                state.ollama.record_token_usage()
        self._send_json(result)

    def handle_ollama_token_usage(self):
        """Ollama token usage snapshot"""
        usage = state.ollama.get_token_usage()
        self._send_json(usage.to_dict())

    def handle_terminal_execute(self):
        """终端命令执行"""
        data = self._read_body()
        command = data.get("command", "")
        args = data.get("args", [])
        timeout = data.get("timeout", 30)

        if not command:
            self._send_error("Missing command parameter")
            return

        cmd = TerminalCommand(
            id=f"api-{uuid.uuid4().hex[:8]}",
            command=command,
            args=args,
            timeout=timeout,
            risk_level=state.terminal._assess_risk(command),
        )
        result = state.terminal.execute(cmd)
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
            self._send_error("Missing plugin_id parameter")
            return

        # 查找 manifest
        manifests = global_plugin_manager.discover()
        manifest = next((m for m in manifests if m.plugin_id == plugin_id), None)
        if not manifest:
            self._send_error(f"Plugin {plugin_id} not found")
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

        entries = state.memory_store.load(mtype)
        self._send_json({
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
        })

    def handle_memory_store(self):
        """存储记忆"""
        data = self._read_body()
        memory_type = data.get("type", "user")
        title = data.get("title", "")
        content_inner = data.get("content", "")
        tags = data.get("tags", [])

        try:
            mtype = MemoryType(memory_type)
        except ValueError:
            mtype = MemoryType.USER

        entry = MemoryEntry.create(mtype, title, content_inner, tags=tags)
        path = state.memory_store.store(entry)
        self._send_json({"success": True, "path": path})

    def handle_events(self):
        """Event history (event_bus module removed, returns empty list for now)"""
        self._send_json({"events": []})

    # ============================================================
    # Orchestrator endpoints
    # ============================================================

    def handle_orchestrator_agents(self):
        """List registered agents"""
        try:
            agents = state.orchestrator.list_agents()
            self._send_json({
                "agents": [a.to_dict() for a in agents],
                "count": len(agents),
            })
        except Exception as e:
            self._send_error(f"Failed to list agents: {e}", 500)

    def handle_orchestrator_history(self):
        """Task execution history"""
        try:
            limit = int(self.headers.get("X-Limit", 10))
            history = state.orchestrator.collect(limit=limit)
            self._send_json({
                "results": [r.to_dict() for r in history],
                "count": len(history),
            })
        except Exception as e:
            self._send_error(f"Failed to collect history: {e}", 500)

    def handle_orchestrator_dispatch(self):
        """Dispatch a task to a registered agent (simulated execution)"""
        data = self._read_body()
        agent_name = data.get("agent_name", "")
        prompt = data.get("prompt", "")
        timeout = data.get("timeout", 30)

        if not agent_name:
            self._send_error("Missing agent_name parameter")
            return
        if not prompt:
            self._send_error("Missing prompt parameter")
            return

        logger.info(f"Mock dispatch to '{agent_name}': {prompt[:100]}")
        print(f"[ORCH] agent={agent_name} prompt={prompt}")

        result = state.orchestrator.dispatch(
            AgentTask(agent_name=agent_name, prompt=prompt, timeout=timeout)
        )
        self._send_json(result.to_dict())


# ============================================================
# Server start
# ============================================================

def run_server(host: str = "127.0.0.1", port: int = 8080):
    """Start J.A.R.V.I.S. API server"""
    server = _IPv4HTTPServer((host, port), JARVISHandler)
    logger.info(f"J.A.R.V.I.S. API server started: http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("server shutting down...")
        server.shutdown()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    run_server()
