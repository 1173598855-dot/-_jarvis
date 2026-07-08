"""
Ollama Manager — 小奕 J.A.R.V.I.S. 本地 LLM 管理器
萃取自 AnythingLLM 的 Ollama 集成逻辑，重写为小奕原生组件

功能：
1. 检测 Ollama 服务状态
2. 列出已安装模型
3. 拉取新模型
4. 发送聊天请求（流式/非流式）
5. 获取系统 GPU 信息

依赖：requests（Python 标准 HTTP 库）
运行：python ollama_manager.py [command]
"""

import os
import requests
import json
import sys
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, asdict
from enum import Enum


class Command(Enum):
    STATUS = "status"
    LIST = "list"
    PULL = "pull"
    CHAT = "chat"
    GPU = "gpu"


@dataclass
class OllamaModel:
    name: str
    size: str
    digest: str
    modified_at: str
    details: Optional[Dict[str, str]] = None

    @classmethod
    def from_api(cls, data: Dict[str, Any]) -> "OllamaModel":
        return cls(
            name=data.get("name", ""),
            size=data.get("size", ""),
            digest=data.get("digest", ""),
            modified_at=data.get("modified_at", ""),
            details=data.get("details", {}),
        )


@dataclass
class OllamaStatus:
    running: bool
    version: Optional[str] = None
    models: List[OllamaModel] = None
    gpu_available: bool = False
    gpu_name: Optional[str] = None

    def __post_init__(self):
        if self.models is None:
            self.models = []


class OllamaManager:
    """小奕本地 LLM 管理器 — 萃取自 AnythingLLM 架构"""

    def __init__(self, base_url: Optional[str] = None, timeout: int = 30):
        # 优先使用环境变量，支持远程 Ollama 实例
        if base_url is None:
            base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._session = requests.Session()

    def _get(self, path: str) -> Dict[str, Any]:
        """内部 GET 请求，统一错误处理"""
        try:
            resp = self._session.get(
                f"{self.base_url}{path}",
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.ConnectionError:
            return {"error": "Ollama 服务未启动，请先执行 ollama serve"}
        except requests.Timeout:
            return {"error": f"请求超时（{self.timeout}s）"}
        except requests.HTTPError as e:
            return {"error": f"HTTP 错误: {e}"}
        except Exception as e:
            return {"error": f"未知错误: {e}"}

    def _post(self, path: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """内部 POST 请求，统一错误处理"""
        try:
            resp = self._session.post(
                f"{self.base_url}{path}",
                json=data,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.ConnectionError:
            return {"error": "Ollama 服务未启动"}
        except requests.Timeout:
            return {"error": f"请求超时（{self.timeout}s）"}
        except requests.HTTPError as e:
            return {"error": f"HTTP 错误: {e}"}
        except Exception as e:
            return {"error": f"未知错误: {e}"}

    def get_status(self) -> OllamaStatus:
        """获取 Ollama 服务状态 + 模型列表 + GPU 信息"""
        version_data = self._get("/api/version")
        if "error" in version_data:
            return OllamaStatus(running=False)

        models_data = self._get("/api/tags")
        models = []
        if "models" in models_data:
            models = [OllamaModel.from_api(m) for m in models_data["models"]]

        gpu_info = self._get("/api/ps")
        gpu_available = "error" not in gpu_info and gpu_info.get("models", [])
        gpu_name = None
        if gpu_available and gpu_info.get("models"):
            gpu_name = gpu_info["models"][0].get("name", "Unknown GPU")

        return OllamaStatus(
            running=True,
            version=version_data.get("version"),
            models=models,
            gpu_available=gpu_available,
            gpu_name=gpu_name,
        )

    def list_models(self) -> List[OllamaModel]:
        """列出所有已安装模型"""
        data = self._get("/api/tags")
        if "error" in data:
            return []
        return [OllamaModel.from_api(m) for m in data.get("models", [])]

    def pull_model(self, model_name: str) -> Dict[str, Any]:
        """拉取模型（流式，实时输出进度）"""
        print(f"正在拉取模型: {model_name}...")
        try:
            resp = self._session.post(
                f"{self.base_url}/api/pull",
                json={"name": model_name, "stream": True},
                timeout=300,
                stream=True,
            )
            resp.raise_for_status()

            for line in resp.iter_lines():
                if line:
                    progress = json.loads(line)
                    status = progress.get("status", "")
                    if status == "success":
                        print(f"✅ 模型 {model_name} 拉取完成")
                    elif "error" in progress:
                        print(f"❌ 错误: {progress['error']}")
                    else:
                        print(f"  {status}")

            return {"success": True, "model": model_name}
        except Exception as e:
            return {"error": str(e)}

    def chat(
        self,
        model: str,
        messages: List[Dict[str, str]],
        stream: bool = False,
    ) -> Dict[str, Any]:
        """发送聊天请求"""
        data = {
            "model": model,
            "messages": messages,
            "stream": stream,
        }
        if stream:
            return self._stream_chat(data)
        return self._post("/api/chat", data)

    def _stream_chat(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """流式聊天响应"""
        try:
            resp = self._session.post(
                f"{self.base_url}/api/chat",
                json=data,
                timeout=self.timeout,
                stream=True,
            )
            resp.raise_for_status()

            full_response = ""
            for line in resp.iter_lines():
                if line:
                    chunk = json.loads(line)
                    if "message" in chunk:
                        content = chunk["message"].get("content", "")
                        print(content, end="", flush=True)
                        full_response += content
                    if chunk.get("done"):
                        print()
                        return {
                            "model": chunk.get("model", ""),
                            "message": {"role": "assistant", "content": full_response},
                            "done": True,
                        }
            return {"message": {"role": "assistant", "content": full_response}, "done": True}
        except Exception as e:
            return {"error": str(e)}

    def stream_chat_generator(self, model: str, messages: List[Dict[str, str]]):
        """
        流式聊天生成器 — 用于 SSE 端点

        Yields:
            (chunk_text: str, is_done: bool)
        """
        data = {
            "model": model,
            "messages": messages,
            "stream": True,
        }
        try:
            resp = self._session.post(
                f"{self.base_url}/api/chat",
                json=data,
                timeout=self.timeout,
                stream=True,
            )
            resp.raise_for_status()

            for line in resp.iter_lines():
                if not line:
                    continue
                chunk = json.loads(line)
                content = chunk.get("message", {}).get("content", "")
                done = chunk.get("done", False)
                if content or done:
                    yield content, done

        except requests.ConnectionError:
            yield "", True
        except requests.Timeout:
            yield "⏱️ 请求超时", True
        except requests.HTTPError as e:
            yield f"HTTP 错误: {e}", True
        except Exception as e:
            yield f"未知错误: {e}", True

    def get_gpu_info(self) -> Dict[str, Any]:
        """获取 GPU 信息"""
        data = self._get("/api/ps")
        if "error" in data:
            return {"available": False, "error": data["error"]}
        models = data.get("models", [])
        if not models:
            return {"available": False, "error": "无 GPU 信息"}
        return {
            "available": True,
            "models": models,
        }

    def to_dict(self, status: OllamaStatus) -> Dict[str, Any]:
        """序列化状态为字典（用于 JSON 输出）"""
        return {
            "running": status.running,
            "version": status.version,
            "models": [asdict(m) for m in status.models],
            "gpu_available": status.gpu_available,
            "gpu_name": status.gpu_name,
        }


def print_status(status: OllamaStatus):
    """格式化输出 Ollama 状态"""
    print("=" * 60)
    print("🤖 Ollama 状态")
    print("=" * 60)

    if not status.running:
        print("❌ 服务状态: 未启动")
        print("   请先执行: ollama serve")
        return

    print(f"✅ 服务状态: 运行中")
    print(f"📦 版本: {status.version or '未知'}")
    print(f"🖥️  GPU: {'✅ ' + status.gpu_name if status.gpu_available else '❌ 未检测到'}")

    print(f"\n📚 已安装模型 ({len(status.models)} 个):")
    if status.models:
        for i, model in enumerate(status.models, 1):
            details = model.details or {}
            size_gb = int(model.size) / (1024**3) if model.size else 0
            print(f"  {i}. {model.name}")
            print(f"     大小: {size_gb:.1f} GB | 修改: {model.modified_at[:10]}")
            if details:
                print(f"     参数: {details.get('parameter_size', '?')} | 量化: {details.get('quantization_level', '?')}")
    else:
        print("  （空）请使用 ollama pull 拉取模型")

    print("=" * 60)


def main():
    """命令行入口"""
    if len(sys.argv) < 2:
        print("用法: python ollama_manager.py <command> [args]")
        print("\n可用命令:")
        print("  status         显示 Ollama 服务状态和模型列表")
        print("  list           列出已安装模型（JSON）")
        print("  pull <model>   拉取模型")
        print("  chat <model>   与模型对话")
        print("  gpu            显示 GPU 信息（JSON）")
        sys.exit(1)

    command_str = sys.argv[1].lower()
    try:
        command = Command(command_str)
    except ValueError:
        print(f"未知命令: {command_str}")
        print(f"可用命令: {[c.value for c in Command]}")
        sys.exit(1)

    manager = OllamaManager()

    if command == Command.STATUS:
        status = manager.get_status()
        print_status(status)
        sys.exit(0 if status.running else 1)

    elif command == Command.LIST:
        models = manager.list_models()
        print(json.dumps([asdict(m) for m in models], indent=2, ensure_ascii=False))

    elif command == Command.PULL:
        if len(sys.argv) < 3:
            print("用法: python ollama_manager.py pull <model_name>")
            sys.exit(1)
        result = manager.pull_model(sys.argv[2])
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif command == Command.CHAT:
        if len(sys.argv) < 3:
            print("用法: python ollama_manager.py chat <model_name>")
            sys.exit(1)
        model = sys.argv[2]
        messages = [{"role": "user", "content": "你好，请介绍一下你自己"}]
        result = manager.chat(model, messages, stream=True)
        if "error" in result:
            print(f"错误: {result['error']}")
            sys.exit(1)

    elif command == Command.GPU:
        gpu_info = manager.get_gpu_info()
        print(json.dumps(gpu_info, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
