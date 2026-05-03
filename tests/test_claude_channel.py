from __future__ import annotations

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import threading

from line.claude_channel import (
    ClaudeChannelClient,
    ClaudeReply,
    parse_sse_payload,
)

TEST_AUTH_VALUE = "test-auth-value"


def test_send_voice_message_posts_json_with_sender_header() -> None:
    received: dict[str, object] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers["content-length"])
            received["path"] = self.path
            received["sender"] = self.headers["x-sender"]
            received["authorization"] = self.headers["authorization"]
            received["body"] = json.loads(self.rfile.read(length).decode("utf-8"))
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true,"chat_id":"run"}')

        def log_message(self, format: str, *args: object) -> None:
            del format, args

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = ClaudeChannelClient(
            base_url=f"http://127.0.0.1:{server.server_port}",
            token=TEST_AUTH_VALUE,
            timeout=1.0,
        )

        response = client.send_voice_message("Check tests", chat_id="run")
    finally:
        server.shutdown()
        thread.join(timeout=1)
        server.server_close()

    assert response == {"ok": True, "chat_id": "run"}
    assert received["path"] == "/voice"
    assert received["sender"] == "local-voice"
    assert received["authorization"] == f"Bearer {TEST_AUTH_VALUE}"
    assert received["body"] == {"text": "Check tests", "chat_id": "run"}


def test_parse_sse_payload_returns_reply_events_only() -> None:
    payload = (
        ": connected\n\n"
        "event: permission_request\n"
        'data: {"request_id":"req_1"}\n\n'
        "event: reply\n"
        'data: {"chat_id":"voice","text":"Accepted","status":"ack","created_at":"2026-05-02T10:00:00Z"}\n\n'
    )

    assert parse_sse_payload(payload) == [
        ClaudeReply(
            chat_id="voice",
            text="Accepted",
            status="ack",
            created_at="2026-05-02T10:00:00Z",
        )
    ]
