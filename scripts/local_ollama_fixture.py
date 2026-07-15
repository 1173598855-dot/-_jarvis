"""Deterministic Ollama-compatible HTTP fixture for local integration checks."""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


MODEL = "fixture"


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
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            self._send_json({"error": "invalid request"}, status=400)
            return

        model = payload.get("model") or MODEL
        if payload.get("stream") is False:
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
