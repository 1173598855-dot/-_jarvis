"""Opt-in integration checks against running local J.A.R.V.I.S. services."""

import argparse
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.request


class ProfileUnavailable(RuntimeError):
    """A required local service is not running or not configured."""


class ProfileFailure(RuntimeError):
    """A running service violated the integration contract."""


class ProfileHttpError(ProfileFailure):
    """An HTTP response failed while preserving status and body details."""

    def __init__(self, url, status, body):
        self.url = url
        self.status = status
        self.body = body
        super().__init__(f"HTTP {status} from {url}: {body[:500]}")


def _request(url, *, method="GET", payload=None, timeout=30):
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method=method,
    )
    try:
        return urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as error:
        with error:
            body = error.read().decode("utf-8", errors="replace")
        raise ProfileHttpError(url, error.code, body) from error
    except urllib.error.URLError as error:
        raise ProfileUnavailable(f"Local service unavailable: {url}: {error}") from error


def _request_json(url, *, method="GET", payload=None, timeout=30):
    with _request(url, method=method, payload=payload, timeout=timeout) as response:
        try:
            return json.load(response)
        except json.JSONDecodeError as error:
            raise ProfileFailure(f"Invalid JSON response from {url}") from error


def parse_sse_payload(payload):
    frames = []
    completed = False
    saw_content = False
    saw_done = False
    for raw_line in payload.splitlines():
        line = raw_line.strip()
        if not line.startswith("data:"):
            continue
        data = line.removeprefix("data:").strip()
        if data == "[DONE]":
            completed = True
            continue
        try:
            frame = json.loads(data)
        except json.JSONDecodeError as error:
            raise ProfileFailure("SSE stream contained invalid JSON") from error
        if isinstance(frame, dict) and "error" in frame:
            raise ProfileFailure(f"SSE stream reported an error: {frame['error']}")
        frames.append(frame)
        if isinstance(frame, dict):
            message = frame.get("message")
            content = (
                message.get("content")
                if isinstance(message, dict)
                else frame.get("content")
            )
            if isinstance(content, str) and content:
                saw_content = True
            if frame.get("done") is True:
                saw_done = True
    if not completed:
        raise ProfileFailure("SSE stream ended without [DONE]")
    if not saw_content:
        raise ProfileFailure("SSE stream returned no assistant content")
    if not saw_done:
        raise ProfileFailure("SSE stream returned no native done frame")
    return frames


def _require(condition, message):
    if not condition:
        raise ProfileFailure(message)


def _select_model(status, explicit_model):
    if explicit_model:
        return explicit_model
    models = status.get("models") or []
    for model in models:
        name = model.get("name") or model.get("model")
        if name:
            return name
    raise ProfileUnavailable("Ollama has no installed model for the SSE check")


def _http_error_code(error):
    try:
        payload = json.loads(error.body)
    except json.JSONDecodeError:
        return None
    details = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(details, dict):
        return details.get("code")
    return None


def _delete_probe(base_url, memory_type, probe_id, cleanup_token, timeout):
    return _request_json(
        f"{base_url}/api/memory/probes/{memory_type}/{probe_id}",
        method="DELETE",
        payload={"cleanup_token": cleanup_token},
        timeout=timeout,
    )


def run_profile(express_url, model=None, timeout=30):
    base_url = express_url.rstrip("/")
    health = _request_json(f"{base_url}/api/health", timeout=timeout)
    _require(health.get("status") == "healthy", "Express health check is not healthy")

    capabilities = _request_json(f"{base_url}/api/capabilities", timeout=timeout)
    core = capabilities.get("core_api") or {}
    if not core.get("configured") or not core.get("available"):
        raise ProfileUnavailable("Core API is not configured and available through Express")

    try:
        ollama = _request_json(f"{base_url}/api/ollama/status", timeout=timeout)
    except ProfileHttpError as error:
        if _http_error_code(error) == "OLLAMA_UNAVAILABLE":
            raise ProfileUnavailable(
                "Ollama is not available through Express"
            ) from error
        raise
    if not ollama.get("running"):
        raise ProfileUnavailable("Ollama is not available through Express")
    selected_model = _select_model(ollama, model)

    plugins = _request_json(f"{base_url}/api/plugins", timeout=timeout)
    _require(isinstance(plugins.get("plugins"), list), "Plugin response has no list")

    marker = f".test-local-integration-{int(time.time() * 1000)}"
    cleanup_token = secrets.token_urlsafe(32)
    memory_type = "project"
    probe_id = None
    result = None
    try:
        stored = _request_json(
            f"{base_url}/api/memory/store",
            method="POST",
            payload={
                "type": memory_type,
                "title": marker,
                "content": "Local integration profile verification",
                "tags": ["test", "integration"],
                "probe_cleanup_token": cleanup_token,
            },
            timeout=timeout,
        )
        _require(stored.get("success") is True, "Memory store did not report success")
        probe_id = stored.get("id")
        _require(bool(probe_id), "Memory store did not return an entry id")
        entries = _request_json(f"{base_url}/api/memory/entries", timeout=timeout)
        _require(
            any(entry.get("title") == marker for entry in entries.get("entries", [])),
            "Stored memory entry was not returned",
        )

        with _request(
            f"{base_url}/api/ollama/chat/stream",
            method="POST",
            payload={
                "model": selected_model,
                "messages": [{"role": "user", "content": "Reply with OK."}],
            },
            timeout=timeout,
        ) as response:
            sse_payload = response.read().decode("utf-8")
        frames = parse_sse_payload(sse_payload)

        result = {
            "status": "passed",
            "express": base_url,
            "model": selected_model,
            "plugins": len(plugins["plugins"]),
            "memory_marker": marker,
            "sse_frames": len(frames),
        }
    except Exception as primary_error:
        if probe_id:
            try:
                _delete_probe(
                    base_url,
                    memory_type,
                    probe_id,
                    cleanup_token,
                    timeout,
                )
            except Exception as cleanup_error:
                primary_error.args = (
                    f"{primary_error} (probe cleanup also failed: {cleanup_error})",
                    *primary_error.args[1:],
                )
        raise
    else:
        if probe_id:
            _delete_probe(
                base_url,
                memory_type,
                probe_id,
                cleanup_token,
                timeout,
            )
        return result


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--express-url",
        default=os.environ.get("JARVIS_EXPRESS_URL", "http://127.0.0.1:9999"),
    )
    parser.add_argument("--model", default=os.environ.get("JARVIS_OLLAMA_MODEL"))
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--require-services", action="store_true")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        result = run_profile(args.express_url, model=args.model, timeout=args.timeout)
    except ProfileUnavailable as error:
        if args.require_services:
            print(f"FAILED: {error}")
            return 1
        print(f"SKIPPED: {error}")
        return 0
    except ProfileFailure as error:
        print(f"FAILED: {error}")
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
