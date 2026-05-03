from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from line.agent_backend import (
    AgentBackendError,
    AgentProcessResult,
    VoiceReply,
    ClaudeCliBackend,
    ClaudeCliConfig,
    CodexAppServerBackend,
    CodexAppServerConfig,
    DEFAULT_VOICE_SYSTEM_PROMPT,
    build_claude_cli_argv,
    build_codex_app_server_argv,
    build_codex_thread_resume_params,
    build_codex_thread_start_params,
    build_codex_turn_start_params,
)


def test_build_claude_cli_argv_uses_haiku_model_by_default() -> None:
    argv = build_claude_cli_argv(ClaudeCliConfig(), "Say briefly: ok")

    assert argv == [
        "claude",
        "--print",
        "--model",
        "haiku",
        "--output-format",
        "text",
        "--append-system-prompt",
        DEFAULT_VOICE_SYSTEM_PROMPT,
        "Say briefly: ok",
    ]


def test_build_claude_cli_argv_allows_custom_voice_prompt() -> None:
    argv = build_claude_cli_argv(
        ClaudeCliConfig(system_prompt="Reply with one word."),
        "status",
    )

    assert argv[-3:] == ["--append-system-prompt", "Reply with one word.", "status"]


def test_build_claude_cli_argv_includes_optional_controls(tmp_path: Path) -> None:
    argv = build_claude_cli_argv(
        ClaudeCliConfig(
            command="claude",
            model="haiku",
            permission_mode="acceptEdits",
            max_budget_usd=0.25,
        ),
        "check tests",
    )

    assert "--permission-mode" in argv
    assert "acceptEdits" in argv
    assert "--max-budget-usd" in argv
    assert "0.25" in argv
    assert argv[-1] == "check tests"


def test_claude_cli_backend_returns_trimmed_stdout(tmp_path: Path) -> None:
    calls: list[tuple[list[str], Path | None, float]] = []

    async def runner(argv: list[str], cwd: Path | None, timeout_seconds: float) -> AgentProcessResult:
        calls.append((argv, cwd, timeout_seconds))
        return AgentProcessResult(returncode=0, stdout="  Done.\n", stderr="")

    backend = ClaudeCliBackend(
        ClaudeCliConfig(cwd=tmp_path, timeout_seconds=12.5),
        process_runner=runner,
    )

    result = asyncio.run(backend.run("status"))

    assert result.reply == "Done."
    assert result.model == "haiku"
    assert calls[0][0][-1] == "status"
    assert calls[0][1] == tmp_path
    assert calls[0][2] == 12.5


def test_claude_cli_backend_raises_on_failed_process() -> None:
    async def runner(argv: list[str], cwd: Path | None, timeout_seconds: float) -> AgentProcessResult:
        del argv, cwd, timeout_seconds
        return AgentProcessResult(returncode=2, stdout="", stderr="model not found")

    backend = ClaudeCliBackend(ClaudeCliConfig(), process_runner=runner)

    with pytest.raises(AgentBackendError, match="model not found"):
        asyncio.run(backend.run("status"))


def test_build_codex_app_server_argv_uses_stdio_transport() -> None:
    argv = build_codex_app_server_argv(CodexAppServerConfig(command="codex"))

    assert argv == ["codex", "app-server", "--listen", "stdio://"]


def test_build_codex_thread_start_params_uses_full_access_without_approvals(tmp_path: Path) -> None:
    params = build_codex_thread_start_params(
        CodexAppServerConfig(cwd=tmp_path, model="gpt-5.5"),
    )

    assert params["cwd"] == str(tmp_path)
    assert params["model"] == "gpt-5.5"
    assert params["approvalPolicy"] == "never"
    assert params["sandbox"] == "danger-full-access"
    assert params["serviceName"] == "line"
    assert params["experimentalRawEvents"] is False
    assert params["persistExtendedHistory"] is True


def test_build_codex_thread_start_params_advertises_voice_reply_dynamic_tool(tmp_path: Path) -> None:
    params = build_codex_thread_start_params(
        CodexAppServerConfig(cwd=tmp_path, model="gpt-5.5"),
    )

    assert params["dynamicTools"] == [
        {
            "name": "reply_to_voice",
            "description": "Send concise user-facing text that should be spoken by the phone UI.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "minLength": 1},
                    "status": {
                        "type": "string",
                        "enum": ["ack", "progress", "done", "error", "reply"],
                    },
                },
                "required": ["text"],
                "additionalProperties": False,
            },
        }
    ]
    assert "reply_to_voice" in params["developerInstructions"]


def test_build_codex_thread_resume_params_uses_existing_thread_and_full_access(tmp_path: Path) -> None:
    params = build_codex_thread_resume_params(
        CodexAppServerConfig(cwd=tmp_path, model="gpt-5.5", thread_id="thread-existing"),
    )

    assert params["threadId"] == "thread-existing"
    assert params["cwd"] == str(tmp_path)
    assert params["model"] == "gpt-5.5"
    assert params["approvalPolicy"] == "never"
    assert params["sandbox"] == "danger-full-access"
    assert params["persistExtendedHistory"] is True
    assert params["excludeTurns"] is True


def test_build_codex_turn_start_params_uses_text_input_and_full_access(tmp_path: Path) -> None:
    params = build_codex_turn_start_params(
        thread_id="thread-1",
        prompt="check tests",
        config=CodexAppServerConfig(cwd=tmp_path, model="gpt-5.5"),
    )

    assert params["threadId"] == "thread-1"
    assert params["input"] == [{"type": "text", "text": "check tests", "text_elements": []}]
    assert params["cwd"] == str(tmp_path)
    assert params["model"] == "gpt-5.5"
    assert params["approvalPolicy"] == "never"
    assert params["sandboxPolicy"] == {"type": "dangerFullAccess"}


def test_codex_app_server_backend_runs_turn_through_json_rpc_transport(tmp_path: Path) -> None:
    transport = ScriptedCodexTransport(
        [
            {"id": 1, "result": {"userAgent": "codex-test"}},
            {
                "id": 2,
                "result": {
                    "thread": {"id": "thread-1"},
                    "model": "gpt-5.5",
                    "modelProvider": "openai",
                    "cwd": str(tmp_path),
                },
            },
            {"id": 3, "result": {"turn": {"id": "turn-1", "status": "running"}}},
            {
                "method": "item/agentMessage/delta",
                "params": {"threadId": "thread-1", "turnId": "turn-1", "itemId": "item-1", "delta": "Done"},
            },
            {
                "method": "item/agentMessage/delta",
                "params": {"threadId": "thread-1", "turnId": "turn-1", "itemId": "item-1", "delta": "."},
            },
            {
                "method": "turn/completed",
                "params": {"threadId": "thread-1", "turn": {"id": "turn-1", "status": "completed"}},
            },
        ]
    )
    backend = CodexAppServerBackend(
        CodexAppServerConfig(cwd=tmp_path, model="gpt-5.5"),
        transport_factory=lambda config: transport,
    )

    result = asyncio.run(backend.run("check tests"))

    assert result.reply == "Done."
    assert result.model == "gpt-5.5"
    assert [message["method"] for message in transport.sent] == ["initialize", "thread/start", "turn/start"]
    assert transport.sent[1]["params"]["approvalPolicy"] == "never"
    assert transport.sent[1]["params"]["sandbox"] == "danger-full-access"
    assert transport.sent[2]["params"]["threadId"] == "thread-1"
    assert transport.sent[2]["params"]["approvalPolicy"] == "never"
    assert transport.sent[2]["params"]["sandboxPolicy"] == {"type": "dangerFullAccess"}


def test_codex_app_server_backend_prefers_reply_to_voice_tool_text(tmp_path: Path) -> None:
    transport = ScriptedCodexTransport(
        [
            {"id": 1, "result": {"userAgent": "codex-test"}},
            {"id": 2, "result": {"thread": {"id": "thread-1"}, "model": "gpt-5.5"}},
            {"id": 3, "result": {"turn": {"id": "turn-1", "status": "running"}}},
            {
                "method": "item/agentMessage/delta",
                "params": {
                    "threadId": "thread-1",
                    "turnId": "turn-1",
                    "itemId": "progress-1",
                    "delta": "I am checking the project now.",
                },
            },
            {
                "id": 41,
                "method": "item/tool/call",
                "params": {
                    "threadId": "thread-1",
                    "turnId": "turn-1",
                    "callId": "call-1",
                    "namespace": None,
                    "tool": "reply_to_voice",
                    "arguments": {"text": "The project is in the MVP folder.", "status": "done"},
                },
            },
            {
                "method": "turn/completed",
                "params": {"threadId": "thread-1", "turn": {"id": "turn-1", "status": "completed"}},
            },
        ]
    )
    backend = CodexAppServerBackend(
        CodexAppServerConfig(cwd=tmp_path, model="gpt-5.5"),
        transport_factory=lambda config: transport,
    )

    result = asyncio.run(backend.run("where is the project?"))

    assert result.reply == "The project is in the MVP folder."
    assert result.full_reply == "I am checking the project now."
    assert result.voice_replies == (VoiceReply(text="The project is in the MVP folder.", status="done"),)
    assert transport.sent[-1] == {
        "id": 41,
        "result": {
            "contentItems": [{"type": "inputText", "text": "Voice reply delivered."}],
            "success": True,
        },
    }


def test_codex_app_server_backend_falls_back_to_last_agent_message(tmp_path: Path) -> None:
    transport = ScriptedCodexTransport(
        [
            {"id": 1, "result": {"userAgent": "codex-test"}},
            {"id": 2, "result": {"thread": {"id": "thread-1"}, "model": "gpt-5.5"}},
            {"id": 3, "result": {"turn": {"id": "turn-1", "status": "running"}}},
            {
                "method": "item/agentMessage/delta",
                "params": {"threadId": "thread-1", "turnId": "turn-1", "itemId": "item-1", "delta": "Intermediate."},
            },
            {
                "method": "item/agentMessage/delta",
                "params": {"threadId": "thread-1", "turnId": "turn-1", "itemId": "item-2", "delta": "Final"},
            },
            {
                "method": "item/agentMessage/delta",
                "params": {"threadId": "thread-1", "turnId": "turn-1", "itemId": "item-2", "delta": "."},
            },
            {
                "method": "turn/completed",
                "params": {"threadId": "thread-1", "turn": {"id": "turn-1", "status": "completed"}},
            },
        ]
    )
    backend = CodexAppServerBackend(
        CodexAppServerConfig(cwd=tmp_path, model="gpt-5.5"),
        transport_factory=lambda config: transport,
    )

    result = asyncio.run(backend.run("answer with final"))

    assert result.reply == "Final."
    assert result.full_reply == "Intermediate.\n\nFinal."


def test_codex_app_server_backend_reuses_thread_for_next_turn(tmp_path: Path) -> None:
    transport = ScriptedCodexTransport(
        [
            {"id": 1, "result": {"userAgent": "codex-test"}},
            {"id": 2, "result": {"thread": {"id": "thread-1"}, "model": "gpt-5.5"}},
            {"id": 3, "result": {"turn": {"id": "turn-1", "status": "running"}}},
            {
                "method": "item/agentMessage/delta",
                "params": {"threadId": "thread-1", "turnId": "turn-1", "itemId": "item-1", "delta": "First"},
            },
            {
                "method": "turn/completed",
                "params": {"threadId": "thread-1", "turn": {"id": "turn-1", "status": "completed"}},
            },
            {"id": 4, "result": {"turn": {"id": "turn-2", "status": "running"}}},
            {
                "method": "item/agentMessage/delta",
                "params": {"threadId": "thread-1", "turnId": "turn-2", "itemId": "item-2", "delta": "Second"},
            },
            {
                "method": "turn/completed",
                "params": {"threadId": "thread-1", "turn": {"id": "turn-2", "status": "completed"}},
            },
        ]
    )
    backend = CodexAppServerBackend(
        CodexAppServerConfig(cwd=tmp_path, model="gpt-5.5"),
        transport_factory=lambda config: transport,
    )

    first = asyncio.run(backend.run("first command"))
    second = asyncio.run(backend.run("second command"))

    assert first.reply == "First"
    assert second.reply == "Second"
    assert [message["method"] for message in transport.sent] == [
        "initialize",
        "thread/start",
        "turn/start",
        "turn/start",
    ]
    assert transport.sent[3]["params"]["threadId"] == "thread-1"


def test_codex_app_server_backend_closes_transport_on_timeout(tmp_path: Path) -> None:
    transport = HangingCodexTransport(
        [
            {"id": 1, "result": {"userAgent": "codex-test"}},
            {"id": 2, "result": {"thread": {"id": "thread-1"}, "model": "gpt-5.5"}},
            {"id": 3, "result": {"turn": {"id": "turn-1", "status": "running"}}},
        ]
    )
    backend = CodexAppServerBackend(
        CodexAppServerConfig(cwd=tmp_path, model="gpt-5.5", timeout_seconds=0.01),
        transport_factory=lambda config: transport,
    )

    with pytest.raises(AgentBackendError, match="timed out"):
        asyncio.run(backend.run("hang"))

    assert transport.closed is True


def test_codex_app_server_backend_resumes_existing_thread_when_thread_id_is_configured(tmp_path: Path) -> None:
    transport = ScriptedCodexTransport(
        [
            {"id": 1, "result": {"userAgent": "codex-test"}},
            {"id": 2, "result": {"thread": {"id": "thread-existing"}, "model": "gpt-5.5"}},
            {"id": 3, "result": {"turn": {"id": "turn-1", "status": "running"}}},
            {
                "method": "item/agentMessage/delta",
                "params": {"threadId": "thread-existing", "turnId": "turn-1", "itemId": "item-1", "delta": "Resume OK"},
            },
            {
                "method": "turn/completed",
                "params": {"threadId": "thread-existing", "turn": {"id": "turn-1", "status": "completed"}},
            },
        ]
    )
    backend = CodexAppServerBackend(
        CodexAppServerConfig(cwd=tmp_path, model="gpt-5.5", thread_id="thread-existing"),
        transport_factory=lambda config: transport,
    )

    result = asyncio.run(backend.run("continue"))

    assert result.reply == "Resume OK"
    assert [message["method"] for message in transport.sent] == ["initialize", "thread/resume", "turn/start"]
    assert transport.sent[1]["params"]["threadId"] == "thread-existing"
    assert transport.sent[2]["params"]["threadId"] == "thread-existing"


def test_codex_app_server_backend_can_use_existing_websocket_endpoint(tmp_path: Path) -> None:
    async def run_case() -> tuple[str, list[dict]]:
        server = FakeCodexWebSocketServer(
            [
                {"id": 1, "result": {"userAgent": "codex-test"}},
                {"id": 2, "result": {"thread": {"id": "thread-existing"}, "model": "gpt-5.5"}},
                {"id": 3, "result": {"turn": {"id": "turn-1", "status": "running"}}},
                {
                    "method": "item/agentMessage/delta",
                    "params": {
                        "threadId": "thread-existing",
                        "turnId": "turn-1",
                        "itemId": "item-1",
                        "delta": "WebSocket OK",
                    },
                },
                {
                    "method": "turn/completed",
                    "params": {"threadId": "thread-existing", "turn": {"id": "turn-1", "status": "completed"}},
                },
            ]
        )
        await server.start()
        try:
            backend = CodexAppServerBackend(
                CodexAppServerConfig(
                    endpoint=server.endpoint,
                    cwd=tmp_path,
                    model="gpt-5.5",
                    thread_id="thread-existing",
                )
            )
            result = await backend.run("continue")
            await backend.aclose()
            return result.reply, server.received
        finally:
            await server.aclose()

    reply, received = asyncio.run(run_case())

    assert reply == "WebSocket OK"
    assert [message["method"] for message in received] == ["initialize", "thread/resume", "turn/start"]


class ScriptedCodexTransport:
    def __init__(self, incoming: list[dict]) -> None:
        self.incoming = list(incoming)
        self.sent: list[dict] = []
        self.closed = False

    async def send(self, message: dict) -> None:
        self.sent.append(message)

    async def receive(self) -> dict:
        if not self.incoming:
            raise AssertionError("No scripted Codex message available")
        return self.incoming.pop(0)

    async def aclose(self) -> None:
        self.closed = True


class HangingCodexTransport(ScriptedCodexTransport):
    async def receive(self) -> dict:
        if self.incoming:
            return self.incoming.pop(0)
        await asyncio.sleep(10)
        raise AssertionError("sleep should be cancelled by backend timeout")


class FakeCodexWebSocketServer:
    def __init__(self, outgoing: list[dict]) -> None:
        self.outgoing = list(outgoing)
        self.received: list[dict] = []
        self.endpoint = ""
        self._server: asyncio.AbstractServer | None = None

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle_client, "127.0.0.1", 0)
        sock = self._server.sockets[0]
        host, port = sock.getsockname()[:2]
        self.endpoint = f"ws://{host}:{port}"

    async def aclose(self) -> None:
        if self._server is None:
            return
        self._server.close()
        await self._server.wait_closed()

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await self._handle_handshake(reader, writer)
        try:
            while self.outgoing:
                message = await _read_client_ws_text(reader)
                self.received.append(message)
                await _write_server_ws_text(writer, self.outgoing.pop(0))
                while self.outgoing and "method" in self.outgoing[0]:
                    await _write_server_ws_text(writer, self.outgoing.pop(0))
        finally:
            writer.close()
            await writer.wait_closed()

    async def _handle_handshake(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        request = b""
        while b"\r\n\r\n" not in request:
            request += await reader.read(1024)
        headers = request.decode("ascii", errors="replace").split("\r\n")
        key = ""
        for header in headers:
            if header.lower().startswith("sec-websocket-key:"):
                key = header.split(":", 1)[1].strip()
                break
        accept = _websocket_accept(key)
        writer.write(
            (
                "HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Accept: {accept}\r\n"
                "\r\n"
            ).encode("ascii")
        )
        await writer.drain()


async def _read_client_ws_text(reader: asyncio.StreamReader) -> dict:
    first = await reader.readexactly(2)
    length = first[1] & 0x7F
    if length == 126:
        length = int.from_bytes(await reader.readexactly(2), "big")
    elif length == 127:
        length = int.from_bytes(await reader.readexactly(8), "big")
    mask = await reader.readexactly(4)
    payload = bytearray(await reader.readexactly(length))
    for index, byte in enumerate(payload):
        payload[index] = byte ^ mask[index % 4]
    return json.loads(payload.decode("utf-8"))


async def _write_server_ws_text(writer: asyncio.StreamWriter, message: dict) -> None:
    payload = json.dumps(message, ensure_ascii=False).encode("utf-8")
    header = bytearray([0x81])
    if len(payload) < 126:
        header.append(len(payload))
    elif len(payload) < 65536:
        header.extend([126, *len(payload).to_bytes(2, "big")])
    else:
        header.extend([127, *len(payload).to_bytes(8, "big")])
    writer.write(bytes(header) + payload)
    await writer.drain()


def _websocket_accept(key: str) -> str:
    import base64
    import hashlib

    digest = hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()
    return base64.b64encode(digest).decode("ascii")
