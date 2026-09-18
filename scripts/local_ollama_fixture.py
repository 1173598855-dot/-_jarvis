"""Deterministic Ollama-compatible HTTP fixture for local integration checks."""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODEL = "fixture"
MAX_FIXTURE_REQUEST_BYTES = 32 * 1024


def _read_bounded_json_body(request: object) -> dict:
    headers = getattr(request, "headers", {})
    try:
        length = int(headers.get("Content-Length", "0"))
    except (AttributeError, TypeError, ValueError, OverflowError) as error:
        raise ValueError("fixture request body length is invalid") from error
    if length < 0 or length > MAX_FIXTURE_REQUEST_BYTES:
        raise ValueError(
            f"fixture request body exceeds {MAX_FIXTURE_REQUEST_BYTES} bytes"
        )
    stream = getattr(request, "rfile", None)
    if stream is None:
        raise ValueError("fixture request body stream is unavailable")
    body = stream.read(length)
    if not isinstance(body, (bytes, bytearray, memoryview)):
        raise ValueError("fixture request body is not bytes")
    payload = json.loads(bytes(body) or b"{}")
    if not isinstance(payload, dict):
        raise ValueError("fixture request body must be an object")
    return payload


def _requested_tool_name(tools: object) -> str | None:
    if not isinstance(tools, list):
        return None
    names = []
    for definition in tools:
        if not isinstance(definition, dict):
            continue
        function = definition.get("function")
        if not isinstance(function, dict):
            continue
        name = function.get("name")
        if isinstance(name, str) and name:
            names.append(name)
    if "repository_metadata" in names:
        return "repository_metadata"
    return names[0] if names else None


def _has_tool_result(messages: object) -> bool:
    return isinstance(messages, list) and any(
        isinstance(message, dict) and message.get("role") == "tool"
        for message in messages
    )


class OllamaFixtureHandler(BaseHTTPRequestHandler):
    server_version = "JARVISOllamaFixture/1.0"

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/api/version":
            self._send_json({"version": "fixture-1.0"})
            return
        if self.path == "/api/tags":
            self._send_json(
                {
                    "models": [
                        {
                            "name": MODEL,
                            "size": "1",
                            "digest": "fixture",
                            "modified_at": "2026-07-13T00:00:00Z",
                        }
                    ]
                }
            )
            return
        if self.path == "/api/ps":
            self._send_json({"models": []})
            return
        self._send_json({"error": "not found"}, status=404)

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/api/chat":
            self._send_json({"error": "not found"}, status=404)
            return

        try:
            payload = _read_bounded_json_body(self)
        except (ValueError, json.JSONDecodeError):
            self._send_json({"error": "invalid request"}, status=400)
            return

        model = payload.get("model") or MODEL
        if payload.get("stream") is False:
            tool_name = _requested_tool_name(payload.get("tools"))
            if tool_name and not _has_tool_result(payload.get("messages")):
                self._send_json(
                    {
                        "model": model,
                        "message": {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "id": "fixture-call-1",
                                    "function": {
                                        "name": tool_name,
                                        "arguments": {},
                                    },
                                }
                            ],
                        },
                        "done": True,
                        "prompt_eval_count": 1,
                        "eval_count": 1,
                    }
                )
                return
            self._send_json(
                {
                    "model": model,
                    "message": {"role": "assistant", "content": "OK"},
                    "done": True,
                    "prompt_eval_count": 1,
                    "eval_count": 1,
                }
            )
            return

        frames = [
            {
                "model": model,
                "message": {"role": "assistant", "content": "OK"},
                "done": False,
            },
            {
                "model": model,
                "message": {"role": "assistant", "content": ""},
                "done": True,
                "prompt_eval_count": 1,
                "eval_count": 1,
            },
        ]
        body = "".join(json.dumps(frame, ensure_ascii=False) + "\n" for frame in frames).encode(
            "utf-8"
        )
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args) -> None:
        return


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=11434)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    server = ThreadingHTTPServer((args.host, args.port), OllamaFixtureHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
