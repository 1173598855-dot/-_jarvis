"""
Ollama Manager ? ?? J.A.R.V.I.S. ?? LLM ???
??? AnythingLLM ? Ollama ??????????????

???
1. ?? Ollama ????
2. ???????
3. ?????
4. ?????????/????
5. ???? GPU ??

???requests?Python ?? HTTP ??
???python ollama_manager.py [command]
"""

import json
import os
import sys
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

import requests

from core.contracts.role_tool_protocol import RoleToolCall, RoleToolProtocolError

TOKEN_USAGE_SAMPLE_LIMIT = 60
MAX_OLLAMA_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_OLLAMA_STREAM_LINE_BYTES = 64 * 1024
MAX_OLLAMA_STREAM_BYTES = 8 * 1024 * 1024
OLLAMA_RESPONSE_CHUNK_BYTES = 8 * 1024


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


@dataclass
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _content_length(response: requests.Response) -> Optional[int]:
    headers = getattr(response, "headers", {})
    try:
        value = headers.get("Content-Length")
    except Exception:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, bytes):
        try:
            value = value.decode("ascii")
        except UnicodeDecodeError:
            return None
    if isinstance(value, str):
        value = value.strip()
        if not value.isdigit():
            return None
        value = int(value)
    elif not isinstance(value, int):
        return None
    return value if value >= 0 else None


def _response_chunk(chunk: object) -> bytes:
    if isinstance(chunk, str):
        return chunk.encode("utf-8")
    if isinstance(chunk, (bytes, bytearray, memoryview)):
        return bytes(chunk)
    raise ValueError("Ollama response contained a non-byte chunk")


def _read_bounded_response(response: requests.Response) -> bytes:
    content_length = _content_length(response)
    if content_length is not None and content_length > MAX_OLLAMA_RESPONSE_BYTES:
        raise ValueError(
            f"Ollama response exceeds {MAX_OLLAMA_RESPONSE_BYTES} bytes"
        )

    body = bytearray()
    for chunk in response.iter_content(
        chunk_size=OLLAMA_RESPONSE_CHUNK_BYTES,
        decode_unicode=False,
    ):
        body.extend(_response_chunk(chunk))
        if len(body) > MAX_OLLAMA_RESPONSE_BYTES:
            raise ValueError(
                f"Ollama response exceeds {MAX_OLLAMA_RESPONSE_BYTES} bytes"
            )
    return bytes(body)


def _iter_bounded_response_lines(response: requests.Response):
    total = 0
    pending = bytearray()
    for chunk in response.iter_content(
        chunk_size=OLLAMA_RESPONSE_CHUNK_BYTES,
        decode_unicode=False,
    ):
        data = _response_chunk(chunk)
        total += len(data)
        if total > MAX_OLLAMA_STREAM_BYTES:
            raise ValueError(
                f"Ollama stream exceeds {MAX_OLLAMA_STREAM_BYTES} bytes"
            )
        pending.extend(data)
        while True:
            newline = pending.find(b"\n")
            if newline < 0:
                break
            line = bytes(pending[:newline])
            del pending[: newline + 1]
            if line.endswith(b"\r"):
                line = line[:-1]
            if len(line) > MAX_OLLAMA_STREAM_LINE_BYTES:
                raise ValueError(
                    "Ollama stream line exceeds "
                    f"{MAX_OLLAMA_STREAM_LINE_BYTES} bytes"
                )
            yield line
        if len(pending) > MAX_OLLAMA_STREAM_LINE_BYTES:
            raise ValueError(
                "Ollama stream line exceeds "
                f"{MAX_OLLAMA_STREAM_LINE_BYTES} bytes"
            )
    if pending:
        if len(pending) > MAX_OLLAMA_STREAM_LINE_BYTES:
            raise ValueError(
                "Ollama stream line exceeds "
                f"{MAX_OLLAMA_STREAM_LINE_BYTES} bytes"
            )
        yield bytes(pending)


def _response_json(response: requests.Response) -> Dict[str, Any]:
    body = _read_bounded_response(response)
    return json.loads(body.decode("utf-8"))


class OllamaManager:
    """???? LLM ??? ? ??? AnythingLLM ??"""

    def __init__(self, base_url: Optional[str] = None, timeout: Optional[int] = 30):
        # ????????????? Ollama ??
        if base_url is None:
            base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._session = requests.Session()
        self._token_usage_lock = threading.Lock()
        self._token_usage = TokenUsage()
        self._latest_token_usage: Optional[Dict[str, Any]] = None
        self._token_usage_samples: deque[Dict[str, Any]] = deque(
            maxlen=TOKEN_USAGE_SAMPLE_LIMIT
        )
        self._token_usage_session_started_at = int(time.time() * 1000)

    def record_token_usage(self, prompt_tokens: int = 0, completion_tokens: int = 0) -> None:
        prompt_tokens = max(prompt_tokens, 0)
        completion_tokens = max(completion_tokens, 0)
        sample = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "timestamp": int(time.time() * 1000),
        }
        with self._token_usage_lock:
            self._token_usage.prompt_tokens += prompt_tokens
            self._token_usage.completion_tokens += completion_tokens
            self._token_usage.total_tokens = (
                self._token_usage.prompt_tokens
                + self._token_usage.completion_tokens
            )
            self._latest_token_usage = sample
            self._token_usage_samples.append(sample)

    def record_token_usage_from_response(self, response: Dict[str, Any]) -> bool:
        """Record token counts from an Ollama response when count fields exist."""
        if not isinstance(response, dict):
            return False

        prompt_tokens = response.get("prompt_eval_count")
        completion_tokens = response.get("eval_count")
        has_native_counts = (
            "prompt_eval_count" in response or "eval_count" in response
        )

        if not has_native_counts:
            usage = response.get("usage")
            if not isinstance(usage, dict):
                return False
            if "prompt_tokens" not in usage and "completion_tokens" not in usage:
                return False
            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)

        try:
            normalized_prompt = int(prompt_tokens or 0)
            normalized_completion = int(completion_tokens or 0)
        except (TypeError, ValueError):
            return False

        self.record_token_usage(normalized_prompt, normalized_completion)
        return True

    def get_token_usage(self) -> TokenUsage:
        with self._token_usage_lock:
            return TokenUsage(
                prompt_tokens=self._token_usage.prompt_tokens,
                completion_tokens=self._token_usage.completion_tokens,
                total_tokens=self._token_usage.total_tokens,
            )

    def get_token_usage_snapshot(self) -> Dict[str, Any]:
        with self._token_usage_lock:
            return {
                "latest": (
                    dict(self._latest_token_usage)
                    if self._latest_token_usage
                    else None
                ),
                "totals": self._token_usage.to_dict(),
                "samples": [
                    dict(sample) for sample in self._token_usage_samples
                ],
                "session_started_at": self._token_usage_session_started_at,
            }

    def _get(self, path: str) -> Dict[str, Any]:
        """?? GET ?????????"""
        try:
            resp = self._session.get(
                f"{self.base_url}{path}",
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return _response_json(resp)
        except requests.ConnectionError:
            return {"error": "Ollama ?????????? ollama serve"}
        except requests.Timeout:
            return {"error": f"?????{self.timeout}s?"}
        except requests.HTTPError as e:
            return {"error": f"HTTP ??: {e}"}
        except Exception as e:
            return {"error": f"????: {e}"}

    def _post(self, path: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """?? POST ?????????"""
        try:
            resp = self._session.post(
                f"{self.base_url}{path}",
                json=data,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return _response_json(resp)
        except requests.ConnectionError:
            return {"error": "Ollama ?????"}
        except requests.Timeout:
            return {"error": f"?????{self.timeout}s?"}
        except requests.HTTPError as e:
            return {"error": f"HTTP ??: {e}"}
        except Exception as e:
            return {"error": f"????: {e}"}

    def get_status(self) -> OllamaStatus:
        """?? Ollama ???? + ???? + GPU ??"""
        version_data = self._get("/api/version")
        if "error" in version_data:
            return OllamaStatus(running=False)

        models_data = self._get("/api/tags")
        models = []
        if "models" in models_data:
            models = [OllamaModel.from_api(m) for m in models_data["models"]]

        gpu_info = self._get("/api/ps")
        gpu_available = (
            "error" not in gpu_info
            and bool(gpu_info.get("models", []))
        )
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
        """?????????"""
        data = self._get("/api/tags")
        if "error" in data:
            return []
        return [OllamaModel.from_api(m) for m in data.get("models", [])]

    def pull_model(self, model_name: str) -> Dict[str, Any]:
        """???????????????"""
        print(f"??????: {model_name}...")
        try:
            resp = self._session.post(
                f"{self.base_url}/api/pull",
                json={"name": model_name, "stream": True},
                timeout=300,
                stream=True,
            )
            resp.raise_for_status()

            for line in _iter_bounded_response_lines(resp):
                if line:
                    progress = json.loads(line)
                    status = progress.get("status", "")
                    if status == "success":
                        print(f"? ?? {model_name} ????")
                    elif "error" in progress:
                        print(f"? ??: {progress['error']}")
                    else:
                        print(f"  {status}")

            return {"success": True, "model": model_name}
        except Exception as e:
            return {"error": str(e)}

    def chat(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        stream: bool = False,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """??????"""
        data = {
            "model": model,
            "messages": messages,
            "stream": stream,
        }
        if tools is not None:
            data["tools"] = tools
        if stream:
            return self._stream_chat(data)
        result = self._post("/api/chat", data)
        if "error" not in result and self._is_valid_chat_response(result):
            self.record_token_usage_from_response(result)
            return result
        if "error" not in result:
            return {"error": "Ollama chat response is invalid"}
        return result

    @staticmethod
    def _is_valid_chat_response(response: Dict[str, Any]) -> bool:
        """Return whether an upstream non-streaming chat response matches the public contract."""
        if not isinstance(response, dict):
            return False
        if not isinstance(response.get("model"), str) or not response["model"]:
            return False
        message = response.get("message")
        if not isinstance(message, dict):
            return False
        if not isinstance(message.get("role"), str) or not message["role"]:
            return False
        content = message.get("content")
        tool_calls = message.get("tool_calls")
        if content is None:
            if not tool_calls:
                return False
        elif not isinstance(content, str):
            return False
        if tool_calls is not None and not isinstance(tool_calls, list):
            return False
        if tool_calls is not None:
            for call_index, tool_call in enumerate(tool_calls):
                try:
                    RoleToolCall.from_ollama(
                        tool_call,
                        round_index=0,
                        call_index=call_index,
                    )
                except RoleToolProtocolError:
                    return False
        if type(response.get("done")) is not bool:
            return False
        for field in ("prompt_eval_count", "eval_count"):
            if field in response and (
                type(response[field]) is not int or response[field] < 0
            ):
                return False
        return True

    def _stream_chat(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """??????"""
        try:
            resp = self._session.post(
                f"{self.base_url}/api/chat",
                json=data,
                timeout=self.timeout,
                stream=True,
            )
            resp.raise_for_status()

            full_response = ""
            for line in _iter_bounded_response_lines(resp):
                if line:
                    chunk = json.loads(line)
                    if "message" in chunk:
                        content = chunk["message"].get("content", "")
                        print(content, end="", flush=True)
                        full_response += content
                    if chunk.get("done"):
                        self.record_token_usage_from_response(chunk)
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
        ??????? ? ?? SSE ??

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

            for line in _iter_bounded_response_lines(resp):
                if not line:
                    continue
                chunk = json.loads(line)
                content = chunk.get("message", {}).get("content", "")
                done = chunk.get("done", False)
                if done:
                    self.record_token_usage_from_response(chunk)
                if content or done:
                    yield content, done

        except requests.ConnectionError:
            yield "", True
        except requests.Timeout:
            yield "?? ????", True
        except requests.HTTPError as e:
            yield f"HTTP ??: {e}", True
        except Exception as e:
            yield f"????: {e}", True

    def get_gpu_info(self) -> Dict[str, Any]:
        """?? GPU ??"""
        data = self._get("/api/ps")
        if "error" in data:
            return {"available": False, "error": data["error"]}
        models = data.get("models", [])
        if not models:
            return {"available": False, "error": "? GPU ??"}
        return {
            "available": True,
            "models": models,
        }

    def to_dict(self, status: OllamaStatus) -> Dict[str, Any]:
        """??????????? JSON ???"""
        return {
            "running": status.running,
            "version": status.version,
            "models": [asdict(m) for m in status.models],
            "gpu_available": status.gpu_available,
            "gpu_name": status.gpu_name,
        }


def print_status(status: OllamaStatus):
    """????? Ollama ??"""
    print("=" * 60)
    print("?? Ollama ??")
    print("=" * 60)

    if not status.running:
        print("? ????: ???")
        print("   ????: ollama serve")
        return

    print("? ????: ???")
    print(f"?? ??: {status.version or '??'}")
    print(f"???  GPU: {'? ' + status.gpu_name if status.gpu_available else '? ????'}")

    print(f"\n?? ????? ({len(status.models)} ?):")
    if status.models:
        for i, model in enumerate(status.models, 1):
            details = model.details or {}
            size_gb = int(model.size) / (1024**3) if model.size else 0
            print(f"  {i}. {model.name}")
            print(f"     ??: {size_gb:.1f} GB | ??: {model.modified_at[:10]}")
            if details:
                print(f"     ??: {details.get('parameter_size', '?')} | ??: {details.get('quantization_level', '?')}")
    else:
        print("  ?????? ollama pull ????")

    print("=" * 60)


def main():
    """?????"""
    if len(sys.argv) < 2:
        print("??: python ollama_manager.py <command> [args]")
        print("\n????:")
        print("  status         ?? Ollama ?????????")
        print("  list           ????????JSON?")
        print("  pull <model>   ????")
        print("  chat <model>   ?????")
        print("  gpu            ?? GPU ???JSON?")
        sys.exit(1)

    command_str = sys.argv[1].lower()
    try:
        command = Command(command_str)
    except ValueError:
        print(f"????: {command_str}")
        print(f"????: {[c.value for c in Command]}")
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
            print("??: python ollama_manager.py pull <model_name>")
            sys.exit(1)
        result = manager.pull_model(sys.argv[2])
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif command == Command.CHAT:
        if len(sys.argv) < 3:
            print("??: python ollama_manager.py chat <model_name>")
            sys.exit(1)
        model = sys.argv[2]
        messages = [{"role": "user", "content": "???????????"}]
        result = manager.chat(model, messages, stream=True)
        if "error" in result:
            print(f"??: {result['error']}")
            sys.exit(1)

    elif command == Command.GPU:
        gpu_info = manager.get_gpu_info()
        print(json.dumps(gpu_info, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
