"""Shared local HTTP fixture for the read-only network.get broker tests."""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LARGE_BODY = b"x" * (70 * 1024)


class _NetworkFixtureHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = self.path
        if path in {"/loop-a", "/loop-b", "/redirect", "/redirect-chain",
                    "/redirect-offsite"}:
            locations = {
                "/loop-a": "/loop-b",
                "/loop-b": "/loop-a",
                "/redirect": "/ok",
                "/redirect-chain": "/redirect",
                "/redirect-offsite": "http://example.invalid/external",
            }
            self.send_response(302)
            self.send_header("Location", locations[path])
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if path == "/ok":
            body = b'{"pong": true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/text":
            body = b"hello network"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/large":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(LARGE_BODY)))
            self.end_headers()
            self.wfile.write(LARGE_BODY)
            return
        if path == "/stream-large":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(LARGE_BODY)
            self.close_connection = True
            return
        if path == "/nonutf8":
            body = bytes([0xFF, 0xFE, 0xD8, 0xFF])
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        body = b"not found"
        self.send_response(404)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:
        return


class NetworkFixtureServer:
    """One thread-owned loopback HTTP fixture bound to an ephemeral port."""

    def __init__(self) -> None:
        self._httpd = ThreadingHTTPServer(
            ("127.0.0.1", 0), _NetworkFixtureHandler
        )
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, daemon=True
        )
        self._thread.start()

    @property
    def base_url(self) -> str:
        host, port = self._httpd.server_address
        return f"http://{host}:{port}"

    def close(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=5)
