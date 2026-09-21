"""Purpose: Shared test helpers: a loopback fake Jev HTTP server with scripted responses, and small criteria."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from jev_screen.criteria import parse_criteria

CRITERIA_DATA = {
    "review": "test review",
    "inclusion": [
        {"id": "population", "statement": "The study population consists of adults with type 2 diabetes",
         "true": "adults with T2D", "false": "anyone else"},
        {"id": "intervention", "statement": "The study evaluates a digital self-management program"},
    ],
    "exclusion": [
        {"id": "animal", "statement": "The study is conducted in animals or in vitro only"},
    ],
    "thresholds": {"include_min": 0.7, "exclude_max": 0.3},
    "unknown_policy": "maybe",
}


def criteria():
    return parse_criteria(json.loads(json.dumps(CRITERIA_DATA)))


def noul_payload(model: str, questions: dict[str, Any], probability: float = 0.9, tokens: int = 120) -> dict:
    return {
        "model": model,
        "answers": {qid: {"type": "noul", "noul": probability} for qid in questions},
        "usage": {"input_tokens": tokens, "output_tokens": 0},
    }


class ScriptedJevServer:
    """Loopback HTTP server that replays a queue of (status, headers, body) responses and records requests."""

    def __init__(self):
        self.responses: list[tuple[int, dict[str, str], Any]] = []
        self.requests: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # keep test output clean
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length)
                with server._lock:
                    server.requests.append({
                        "path": self.path,
                        "authorization": self.headers.get("Authorization"),
                        "body": json.loads(raw.decode("utf-8")) if raw else None,
                    })
                    if server.responses:
                        status, headers, body = server.responses.pop(0)
                    else:
                        status, headers, body = 500, {}, {"error": "no scripted response"}
                payload = body if isinstance(body, (bytes, bytearray)) else json.dumps(body).encode("utf-8")
                self.send_response(status)
                for key, value in headers.items():
                    self.send_header(key, value)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=lambda: self.httpd.serve_forever(poll_interval=0.02), daemon=True)

    @property
    def endpoint(self) -> str:
        host, port = self.httpd.server_address[:2]
        return f"http://{host}:{port}/v1/systemone"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()
