from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass
import hashlib
import inspect
import json
import os
from pathlib import Path
import ssl
from typing import Any, Awaitable, Callable, Protocol
from urllib.parse import urlparse

from line.agent_backends.base import (
    AgentBackendError,
    AgentJobResult,
    DEFAULT_VOICE_SYSTEM_PROMPT,
    VOICE_REPLY_STATUSES,
    VOICE_REPLY_TOOL_NAME,
    VoiceReply,
)


@dataclass(frozen=True)
class CodexTurnResult:
    agent_messages: tuple[str, ...]
    voice_replies: tuple[VoiceReply, ...]

    @property
    def full_reply(self) -> str:
        return "\n\n".join(self.agent_messages).strip()

    @property
    def final_agent_message(self) -> str:
        for message in reversed(self.agent_messages):
            clean = message.strip()
            if clean:
                return clean
        return ""


@dataclass(frozen=True)
class CodexAppServerConfig:
    command: str = "codex"
    endpoint: str | None = None
    thread_id: str | None = None
    cwd: Path | None = None
    model: str | None = None
    approval_policy: str = "never"
    sandbox_mode: str = "danger-full-access"
    service_name: str = "line"
    timeout_seconds: float = 900.0
    developer_instructions: str | None = DEFAULT_VOICE_SYSTEM_PROMPT
    voice_reply_tool: bool = True


class CodexJsonRpcTransport(Protocol):
    async def send(self, message: dict[str, Any]) -> None: ...

    async def receive(self) -> dict[str, Any]: ...

    async def aclose(self) -> None: ...


CodexTransportFactory = Callable[
    [CodexAppServerConfig],
    CodexJsonRpcTransport | Awaitable[CodexJsonRpcTransport],
]


class CodexAppServerBackend:
    def __init__(
        self,
        config: CodexAppServerConfig,
        transport_factory: CodexTransportFactory | None = None,
    ) -> None:
        self.config = config
        self._transport_factory = transport_factory or start_codex_transport
        self._client: CodexAppServerClient | None = None
        self._thread_id: str | None = None
        self._lock: asyncio.Lock | None = None
        self._lock_loop: asyncio.AbstractEventLoop | None = None

    @property
    def label(self) -> str:
        return "codex"

    @property
    def model(self) -> str:
        return self.config.model or "codex-default"

    async def run(self, prompt: str) -> AgentJobResult:
        try:
            return await asyncio.wait_for(self._run_serialized(prompt), self.config.timeout_seconds)
        except TimeoutError as error:
            await self.aclose()
            raise AgentBackendError(f"Codex app-server timed out after {self.config.timeout_seconds:g}s") from error

    async def _run_serialized(self, prompt: str) -> AgentJobResult:
        lock = self._get_lock()
        async with lock:
            client = await self._get_client()
            await self._ensure_thread(client)
            turn_result = await client.request(
                "turn/start",
                build_codex_turn_start_params(
                    thread_id=self._thread_id,
                    prompt=prompt,
                    config=self.config,
                ),
            )
            turn_id = _extract_turn_id(turn_result)
            turn = await client.wait_for_turn_completed(self._thread_id, turn_id)
            spoken_reply = select_codex_spoken_reply(turn)
            full_reply = turn.full_reply
            return AgentJobResult(
                prompt=prompt,
                reply=spoken_reply,
                model=self.model,
                stdout=full_reply or spoken_reply,
                stderr="",
                full_reply=full_reply,
                spoken_reply=spoken_reply,
                voice_replies=turn.voice_replies,
            )

    async def _get_client(self) -> "CodexAppServerClient":
        if self._client is not None:
            return self._client
        transport_or_awaitable = self._transport_factory(self.config)
        transport = (
            await transport_or_awaitable
            if inspect.isawaitable(transport_or_awaitable)
            else transport_or_awaitable
        )
        client = CodexAppServerClient(transport)
        await client.initialize()
        self._client = client
        return client

    def _get_lock(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        if self._lock is None or self._lock_loop is not loop:
            self._lock = asyncio.Lock()
            self._lock_loop = loop
        return self._lock

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        self._thread_id = None

    async def _ensure_thread(self, client: "CodexAppServerClient") -> None:
        if self._thread_id is not None:
            return
        if self.config.thread_id:
            thread_result = await client.request("thread/resume", build_codex_thread_resume_params(self.config))
        else:
            thread_result = await client.request("thread/start", build_codex_thread_start_params(self.config))
        self._thread_id = _extract_thread_id(thread_result)


def build_codex_app_server_argv(config: CodexAppServerConfig) -> list[str]:
    return [config.command, "app-server", "--listen", "stdio://"]


def build_codex_thread_start_params(config: CodexAppServerConfig) -> dict[str, Any]:
    params: dict[str, Any] = {
        "approvalPolicy": config.approval_policy,
        "sandbox": config.sandbox_mode,
        "serviceName": config.service_name,
        "experimentalRawEvents": False,
        "persistExtendedHistory": True,
    }
    if config.cwd is not None:
        params["cwd"] = str(config.cwd)
    if config.model:
        params["model"] = config.model
    if config.developer_instructions:
        params["developerInstructions"] = config.developer_instructions
    if config.voice_reply_tool:
        params["dynamicTools"] = [build_voice_reply_dynamic_tool()]
    return params


def build_codex_thread_resume_params(config: CodexAppServerConfig) -> dict[str, Any]:
    if not config.thread_id:
        raise ValueError("Codex thread_id is required for thread/resume")
    params: dict[str, Any] = {
        "threadId": config.thread_id,
        "approvalPolicy": config.approval_policy,
        "sandbox": config.sandbox_mode,
        "excludeTurns": True,
        "persistExtendedHistory": True,
    }
    if config.cwd is not None:
        params["cwd"] = str(config.cwd)
    if config.model:
        params["model"] = config.model
    if config.developer_instructions:
        params["developerInstructions"] = config.developer_instructions
    return params


def build_codex_turn_start_params(*, thread_id: str, prompt: str, config: CodexAppServerConfig) -> dict[str, Any]:
    params: dict[str, Any] = {
        "threadId": thread_id,
        "input": [{"type": "text", "text": prompt, "text_elements": []}],
        "approvalPolicy": config.approval_policy,
        "sandboxPolicy": _sandbox_policy(config.sandbox_mode),
    }
    if config.cwd is not None:
        params["cwd"] = str(config.cwd)
    if config.model:
        params["model"] = config.model
    return params


def build_voice_reply_dynamic_tool() -> dict[str, Any]:
    return {
        "name": VOICE_REPLY_TOOL_NAME,
        "description": "Send concise user-facing text that should be spoken by the phone UI.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "minLength": 1},
                "status": {
                    "type": "string",
                    "enum": list(VOICE_REPLY_STATUSES),
                },
            },
            "required": ["text"],
            "additionalProperties": False,
        },
    }


def select_codex_spoken_reply(turn: CodexTurnResult) -> str:
    for reply in reversed(turn.voice_replies):
        if reply.status in {"done", "reply", "error"} and reply.text.strip():
            return reply.text.strip()
    for reply in reversed(turn.voice_replies):
        if reply.text.strip():
            return reply.text.strip()
    return turn.final_agent_message or "Codex completed the task without a text reply."


def _sandbox_policy(sandbox_mode: str) -> dict[str, Any]:
    if sandbox_mode == "danger-full-access":
        return {"type": "dangerFullAccess"}
    if sandbox_mode == "read-only":
        return {"type": "readOnly", "networkAccess": False}
    raise ValueError(f"Unsupported Codex sandbox mode for voice backend: {sandbox_mode}")


async def start_codex_transport(config: CodexAppServerConfig) -> CodexJsonRpcTransport:
    if config.endpoint:
        return await CodexAppServerWebSocketTransport.connect(config.endpoint)
    return await CodexAppServerProcessTransport.start(config)


class CodexAppServerProcessTransport:
    def __init__(self, process: asyncio.subprocess.Process) -> None:
        self.process = process

    @classmethod
    async def start(cls, config: CodexAppServerConfig) -> "CodexAppServerProcessTransport":
        process = await asyncio.create_subprocess_exec(
            *build_codex_app_server_argv(config),
            cwd=str(config.cwd) if config.cwd is not None else None,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        return cls(process)

    async def send(self, message: dict[str, Any]) -> None:
        if self.process.stdin is None:
            raise AgentBackendError("Codex app-server stdin is unavailable")
        body = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.process.stdin.write(body + b"\n")
        await self.process.stdin.drain()

    async def receive(self) -> dict[str, Any]:
        if self.process.stdout is None:
            raise AgentBackendError("Codex app-server stdout is unavailable")
        line = await self.process.stdout.readline()
        if not line:
            detail = await self._stderr_tail()
            suffix = f": {detail}" if detail else ""
            raise AgentBackendError(f"Codex app-server closed stdout{suffix}")
        try:
            payload = json.loads(line.decode("utf-8"))
        except json.JSONDecodeError as error:
            raise AgentBackendError(f"Codex app-server returned invalid JSON: {line!r}") from error
        if not isinstance(payload, dict):
            raise AgentBackendError(f"Codex app-server returned non-object JSON: {payload!r}")
        return payload

    async def aclose(self) -> None:
        if self.process.returncode is not None:
            return
        self.process.terminate()
        try:
            await asyncio.wait_for(self.process.wait(), 2.0)
        except TimeoutError:
            self.process.kill()
            await self.process.wait()

    async def _stderr_tail(self) -> str:
        if self.process.stderr is None:
            return ""
        stderr = await self.process.stderr.read()
        return stderr.decode("utf-8", errors="replace").strip()[-500:]


class CodexAppServerWebSocketTransport:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, endpoint: str) -> None:
        self.reader = reader
        self.writer = writer
        self.endpoint = endpoint

    @classmethod
    async def connect(cls, endpoint: str) -> "CodexAppServerWebSocketTransport":
        parsed = urlparse(endpoint)
        if parsed.scheme not in {"ws", "wss"}:
            raise AgentBackendError(f"Unsupported Codex endpoint scheme: {parsed.scheme or endpoint}")
        host = parsed.hostname
        if not host:
            raise AgentBackendError(f"Codex endpoint must include host: {endpoint}")
        port = parsed.port or (443 if parsed.scheme == "wss" else 80)
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        ssl_context = ssl.create_default_context() if parsed.scheme == "wss" else None
        reader, writer = await asyncio.open_connection(host, port, ssl=ssl_context)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        writer.write(request.encode("ascii"))
        await writer.drain()
        response = await _read_http_headers(reader)
        _validate_websocket_handshake(response, key, endpoint)
        return cls(reader, writer, endpoint)

    async def send(self, message: dict[str, Any]) -> None:
        payload = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self._write_frame(opcode=0x1, payload=payload)
        await self.writer.drain()

    async def receive(self) -> dict[str, Any]:
        while True:
            opcode, payload = await self._read_frame()
            if opcode == 0x1:
                try:
                    message = json.loads(payload.decode("utf-8"))
                except json.JSONDecodeError as error:
                    raise AgentBackendError(f"Codex endpoint returned invalid JSON: {payload!r}") from error
                if not isinstance(message, dict):
                    raise AgentBackendError(f"Codex endpoint returned non-object JSON: {message!r}")
                return message
            if opcode == 0x8:
                raise AgentBackendError(f"Codex endpoint closed WebSocket: {self.endpoint}")
            if opcode == 0x9:
                self._write_frame(opcode=0xA, payload=payload)
                await self.writer.drain()

    async def aclose(self) -> None:
        if not self.writer.is_closing():
            try:
                self._write_frame(opcode=0x8, payload=b"")
                await self.writer.drain()
            except OSError:
                pass
        self.writer.close()
        try:
            await self.writer.wait_closed()
        except OSError:
            pass

    def _write_frame(self, *, opcode: int, payload: bytes) -> None:
        mask = os.urandom(4)
        header = bytearray([0x80 | opcode])
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.extend([0x80 | 126])
            header.extend(length.to_bytes(2, "big"))
        else:
            header.extend([0x80 | 127])
            header.extend(length.to_bytes(8, "big"))
        masked = bytearray(payload)
        for index, byte in enumerate(masked):
            masked[index] = byte ^ mask[index % 4]
        self.writer.write(bytes(header) + mask + bytes(masked))

    async def _read_frame(self) -> tuple[int, bytes]:
        first = await self.reader.readexactly(2)
        opcode = first[0] & 0x0F
        masked = bool(first[1] & 0x80)
        length = first[1] & 0x7F
        if length == 126:
            length = int.from_bytes(await self.reader.readexactly(2), "big")
        elif length == 127:
            length = int.from_bytes(await self.reader.readexactly(8), "big")
        mask = await self.reader.readexactly(4) if masked else b""
        payload = bytearray(await self.reader.readexactly(length))
        if masked:
            for index, byte in enumerate(payload):
                payload[index] = byte ^ mask[index % 4]
        return opcode, bytes(payload)


async def _read_http_headers(reader: asyncio.StreamReader) -> bytes:
    response = b""
    while b"\r\n\r\n" not in response:
        chunk = await reader.read(1024)
        if not chunk:
            raise AgentBackendError("Codex endpoint closed during WebSocket handshake")
        response += chunk
        if len(response) > 65536:
            raise AgentBackendError("Codex endpoint WebSocket handshake response is too large")
    return response


def _validate_websocket_handshake(response: bytes, key: str, endpoint: str) -> None:
    text = response.decode("ascii", errors="replace")
    lines = text.split("\r\n")
    if not lines or " 101 " not in lines[0]:
        raise AgentBackendError(f"Codex endpoint refused WebSocket upgrade: {lines[0] if lines else endpoint}")
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if ":" in line:
            name, value = line.split(":", 1)
            headers[name.strip().lower()] = value.strip()
    expected = _websocket_accept(key)
    actual = headers.get("sec-websocket-accept", "")
    if actual != expected:
        raise AgentBackendError(f"Codex endpoint returned invalid WebSocket accept header: {endpoint}")


def _websocket_accept(key: str) -> str:
    digest = hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()
    return base64.b64encode(digest).decode("ascii")


class CodexAppServerClient:
    def __init__(self, transport: CodexJsonRpcTransport) -> None:
        self.transport = transport
        self._next_request_id = 1
        self._message_parts: dict[tuple[str, str, str], list[str]] = {}
        self._voice_replies: dict[tuple[str, str], list[VoiceReply]] = {}

    async def initialize(self) -> dict[str, Any]:
        return await self.request(
            "initialize",
            {
                "clientInfo": {
                    "name": "line",
                    "title": "line",
                    "version": "0.1.0",
                },
                "capabilities": {"experimentalApi": True},
            },
        )

    async def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        request_id = self._next_request_id
        self._next_request_id += 1
        message: dict[str, Any] = {"id": request_id, "method": method}
        if params is not None:
            message["params"] = params
        await self.transport.send(message)
        while True:
            incoming = await self.transport.receive()
            if incoming.get("id") == request_id and "method" not in incoming:
                return _response_result(method, incoming)
            await self._handle_incoming(incoming)

    async def wait_for_turn_completed(self, thread_id: str, turn_id: str) -> CodexTurnResult:
        key = (thread_id, turn_id)
        while True:
            incoming = await self.transport.receive()
            method = str(incoming.get("method", ""))
            params = incoming.get("params") if isinstance(incoming.get("params"), dict) else {}
            await self._handle_incoming(incoming)
            if method == "turn/completed" and params.get("threadId") == thread_id:
                turn = params.get("turn") if isinstance(params.get("turn"), dict) else {}
                if turn.get("id") != turn_id:
                    continue
                status = str(turn.get("status", ""))
                if status not in {"completed", "succeeded", "success", ""}:
                    raise AgentBackendError(f"Codex turn finished with status: {status}")
                return CodexTurnResult(
                    agent_messages=self._pop_agent_messages(thread_id, turn_id),
                    voice_replies=tuple(self._voice_replies.pop(key, [])),
                )

    async def aclose(self) -> None:
        await self.transport.aclose()

    async def _handle_incoming(self, message: dict[str, Any]) -> None:
        if "error" in message:
            raise AgentBackendError(f"Codex app-server error: {_format_rpc_error(message['error'])}")
        method = message.get("method")
        if method is None:
            return
        if "id" in message:
            if method == "item/tool/call":
                await self._handle_dynamic_tool_call(message)
                return
            raise AgentBackendError(f"Codex app-server requested unsupported client action: {method}")
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        if method == "error":
            raise AgentBackendError(f"Codex app-server error: {_format_rpc_error(params.get('error', params))}")
        if method == "item/agentMessage/delta":
            thread_id = params.get("threadId")
            turn_id = params.get("turnId")
            item_id = params.get("itemId")
            delta = params.get("delta")
            if isinstance(thread_id, str) and isinstance(turn_id, str) and isinstance(delta, str):
                item_key = item_id if isinstance(item_id, str) and item_id else "unknown"
                self._message_parts.setdefault((thread_id, turn_id, item_key), []).append(delta)

    async def _handle_dynamic_tool_call(self, message: dict[str, Any]) -> None:
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        request_id = message.get("id")
        thread_id = params.get("threadId")
        turn_id = params.get("turnId")
        tool = params.get("tool")
        arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        if (
            isinstance(request_id, int | str)
            and isinstance(thread_id, str)
            and isinstance(turn_id, str)
            and tool == VOICE_REPLY_TOOL_NAME
        ):
            text = str(arguments.get("text", "")).strip()
            status = str(arguments.get("status", "reply")).strip()
            if status not in VOICE_REPLY_STATUSES:
                status = "reply"
            if text:
                self._voice_replies.setdefault((thread_id, turn_id), []).append(
                    VoiceReply(text=text, status=status)
                )
                await self.transport.send(_dynamic_tool_response(request_id, "Voice reply delivered.", success=True))
                return
            await self.transport.send(_dynamic_tool_response(request_id, "Voice reply text is empty.", success=False))
            return
        if isinstance(request_id, int | str):
            await self.transport.send(
                _dynamic_tool_response(request_id, f"Unsupported dynamic tool: {tool}", success=False)
            )
            return
        raise AgentBackendError(f"Codex app-server requested invalid dynamic tool call: {message!r}")

    def _pop_agent_messages(self, thread_id: str, turn_id: str) -> tuple[str, ...]:
        messages: list[str] = []
        for key, parts in list(self._message_parts.items()):
            key_thread_id, key_turn_id, _item_id = key
            if key_thread_id == thread_id and key_turn_id == turn_id:
                text = "".join(parts).strip()
                if text:
                    messages.append(text)
                del self._message_parts[key]
        return tuple(messages)


def _dynamic_tool_response(request_id: int | str, text: str, *, success: bool) -> dict[str, Any]:
    return {
        "id": request_id,
        "result": {
            "contentItems": [{"type": "inputText", "text": text}],
            "success": success,
        },
    }


def _response_result(method: str, response: dict[str, Any]) -> dict[str, Any]:
    if "error" in response:
        raise AgentBackendError(f"Codex app-server {method} failed: {_format_rpc_error(response['error'])}")
    result = response.get("result", {})
    if not isinstance(result, dict):
        raise AgentBackendError(f"Codex app-server {method} returned invalid result: {result!r}")
    return result


def _extract_thread_id(result: dict[str, Any]) -> str:
    thread = result.get("thread")
    if not isinstance(thread, dict) or not isinstance(thread.get("id"), str):
        raise AgentBackendError(f"Codex thread/start returned no thread id: {result!r}")
    return thread["id"]


def _extract_turn_id(result: dict[str, Any]) -> str:
    turn = result.get("turn")
    if not isinstance(turn, dict) or not isinstance(turn.get("id"), str):
        raise AgentBackendError(f"Codex turn/start returned no turn id: {result!r}")
    return turn["id"]


def _format_rpc_error(error: Any) -> str:
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
    return str(error)
