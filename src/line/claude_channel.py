from __future__ import annotations

from dataclasses import dataclass
import json
import socket
import urllib.error
import urllib.request


class ClaudeChannelError(RuntimeError):
    pass


@dataclass(frozen=True)
class ClaudeChannelClient:
    base_url: str = "http://127.0.0.1:8790"
    token: str | None = None
    sender: str = "local-voice"
    timeout: float = 5.0

    def send_voice_message(self, text: str, chat_id: str = "voice") -> dict[str, object]:
        payload = json.dumps({"text": text, "chat_id": chat_id}, ensure_ascii=False).encode("utf-8")
        headers = {
            "content-type": "application/json",
            "x-sender": self.sender,
        }
        if self.token:
            headers["authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(
            f"{self.base_url.rstrip('/')}/voice",
            data=payload,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8")
        except urllib.error.URLError as error:
            raise ClaudeChannelError(f"Claude channel request failed: {error}") from error

        try:
            data = json.loads(body)
        except json.JSONDecodeError as error:
            raise ClaudeChannelError("Claude channel returned non-JSON response") from error
        if not isinstance(data, dict):
            raise ClaudeChannelError("Claude channel returned unexpected response")
        if data.get("ok") is False:
            raise ClaudeChannelError(str(data.get("error") or "Claude channel rejected request"))
        return data


@dataclass(frozen=True)
class ClaudeReply:
    chat_id: str
    text: str
    status: str = "reply"
    created_at: str | None = None


@dataclass(frozen=True)
class ClaudeReplyStream:
    base_url: str = "http://127.0.0.1:8790"
    token: str | None = None
    sender: str = "local-voice"
    timeout: float = 1.0

    def iter_replies(self):
        while True:
            headers = {"x-sender": self.sender}
            if self.token:
                headers["authorization"] = f"Bearer {self.token}"
            request = urllib.request.Request(
                f"{self.base_url.rstrip('/')}/events",
                headers=headers,
                method="GET",
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    yield from _iter_reply_lines(response)
            except (TimeoutError, socket.timeout, urllib.error.URLError):
                continue


def parse_sse_payload(payload: str) -> list[ClaudeReply]:
    replies: list[ClaudeReply] = []
    for block in payload.split("\n\n"):
        reply = _parse_sse_block(block.splitlines())
        if reply is not None:
            replies.append(reply)
    return replies


def _iter_reply_lines(response) -> ClaudeReply:
    event_lines: list[str] = []
    for raw_line in response:
        line = raw_line.decode("utf-8").rstrip("\r\n")
        if line:
            event_lines.append(line)
            continue
        reply = _parse_sse_block(event_lines)
        event_lines = []
        if reply is not None:
            yield reply


def _parse_sse_block(lines: list[str]) -> ClaudeReply | None:
    event_name = "message"
    data_lines: list[str] = []
    for line in lines:
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event_name = line.removeprefix("event:").strip()
        elif line.startswith("data:"):
            data_lines.append(line.removeprefix("data:").strip())

    if event_name != "reply" or not data_lines:
        return None
    payload = json.loads("\n".join(data_lines))
    if not isinstance(payload, dict):
        return None
    text = str(payload.get("text") or "").strip()
    if not text:
        return None
    return ClaudeReply(
        chat_id=str(payload.get("chat_id") or "voice"),
        text=text,
        status=str(payload.get("status") or "reply"),
        created_at=str(payload["created_at"]) if payload.get("created_at") else None,
    )
