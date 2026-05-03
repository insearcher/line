import asyncio
import json
from pathlib import Path
import pytest

from line.agent_backend import AgentJobResult
from line.capture import CaptureMode
from line.cli import build_parser, main, run_agent_once, run_dry_run

TEST_AUTH_VALUE = "test-auth-value"
TEST_LIVEKIT_HMAC = "0" * 32
TEST_LIVEKIT_KEY = "test-livekit-value"
TEST_STT_KEY = "test-stt-value"
TEST_TTS_KEY = "test-tts-value"
TEST_TTS_VOICE = "test-tts-voice"
TEST_TTS_MODEL = "test-tts-model"


def test_dry_run_dispatch_writes_queue(tmp_path: Path) -> None:
    result = run_dry_run(
        text="Ask Codex to check the LiveKit worker",
        queue_path=tmp_path / "tasks.jsonl",
    )

    payload = json.loads(result)

    assert payload["intent"] == "dispatch"
    assert payload["queued_task"]["task_text"] == "check the livekit worker"
    assert payload["spoken_reply"].startswith("Accepted")


def test_dry_run_cancel_does_not_write_queue(tmp_path: Path) -> None:
    queue_path = tmp_path / "tasks.jsonl"

    result = run_dry_run(text="cancel", queue_path=queue_path)

    payload = json.loads(result)
    assert payload["intent"] == "cancel"
    assert payload["queued_task"] is None
    assert not queue_path.exists()


def test_config_check_prints_missing_env_without_traceback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for key in (
        "LIVEKIT_URL",
        "LIVEKIT_API_KEY",
        "LIVEKIT_API_SECRET",
        "DEEPGRAM_API_KEY",
        "ELEVENLABS_API_KEY",
        "ELEVENLABS_VOICE_ID",
        "ELEVENLABS_MODEL",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(
        "sys.argv",
        ["line", "config-check", "--env", str(tmp_path / "missing.env")],
    )

    with pytest.raises(SystemExit) as error:
        main()

    assert error.value.code == 2
    captured = capsys.readouterr()
    assert "Missing required environment variables" in captured.err
    assert "Traceback" not in captured.err


def test_parser_accepts_demo_server_command() -> None:
    args = build_parser().parse_args(
        [
            "demo-server",
            "--host",
            "127.0.0.1",
            "--port",
            "8787",
            "--room",
            "line-dev",
            "--identity",
            "mac-test",
        ]
    )

    assert args.command == "demo-server"
    assert args.host == "127.0.0.1"
    assert args.port == 8787
    assert args.room == "line-dev"
    assert args.identity == "mac-test"


def test_parser_accepts_pair_command() -> None:
    args = build_parser().parse_args(
        [
            "pair",
            "--server-url",
            "http://100.127.216.66:8787",
            "--state",
            "data/pairing_state.json",
            "--ttl",
            "300",
        ]
    )

    assert args.command == "pair"
    assert args.server_url == "http://100.127.216.66:8787"
    assert args.state == Path("data/pairing_state.json")
    assert args.ttl == 300


def test_parser_accepts_lowlevel_worker_command() -> None:
    args = build_parser().parse_args(
        [
            "lowlevel-worker",
            "--room",
            "line-dev",
            "--identity",
            "line-worker",
            "--claude-channel-url",
            "http://127.0.0.1:8790",
            "--claude-channel-token",
            TEST_AUTH_VALUE,
            "--agent-backend",
            "claude-cli",
            "--agent-model",
            "haiku",
            "--agent-cwd",
            "/tmp",
            "--agent-permission-mode",
            "acceptEdits",
            "--agent-runs",
            "data/runs.jsonl",
            "--capture-mode",
            "markers",
            "--capture-wake-word",
            "codex",
            "--capture-start",
            "start command",
            "--capture-submit",
            "send command",
            "--capture-cancel",
            "cancel",
            "--capture-silence-timeout",
            "5",
        ]
    )

    assert args.command == "lowlevel-worker"
    assert args.room == "line-dev"
    assert args.identity == "line-worker"
    assert args.claude_channel_url == "http://127.0.0.1:8790"
    assert args.claude_channel_token == TEST_AUTH_VALUE
    assert args.agent_backend == "claude-cli"
    assert args.agent_model == "haiku"
    assert args.agent_cwd == Path("/tmp")
    assert args.agent_permission_mode == "acceptEdits"
    assert args.agent_runs == Path("data/runs.jsonl")
    assert args.capture_mode == CaptureMode.MARKERS
    assert args.capture_wake_word == "codex"
    assert args.capture_start == "start command"
    assert args.capture_submit == "send command"
    assert args.capture_cancel == "cancel"
    assert args.capture_silence_timeout == 5.0


def test_parser_uses_practical_marker_capture_timeout_default() -> None:
    args = build_parser().parse_args(["lowlevel-worker"])

    assert args.capture_silence_timeout == 20.0


def test_parser_uses_single_word_cancel_default() -> None:
    args = build_parser().parse_args(["lowlevel-worker"])

    assert args.capture_cancel == "cancel"


def test_parser_accepts_claude_channel_send_command() -> None:
    args = build_parser().parse_args(
        [
            "claude-channel-send",
            "Check tests",
            "--url",
            "http://127.0.0.1:8790",
            "--token",
            TEST_AUTH_VALUE,
        ]
    )

    assert args.command == "claude-channel-send"
    assert args.text == "Check tests"
    assert args.url == "http://127.0.0.1:8790"
    assert args.token == TEST_AUTH_VALUE


def test_parser_accepts_agent_run_command() -> None:
    args = build_parser().parse_args(
        [
            "agent-run",
            "Say ok",
            "--agent-backend",
            "claude-cli",
            "--agent-model",
            "haiku",
            "--agent-cwd",
            "/tmp",
        ]
    )

    assert args.command == "agent-run"
    assert args.text == "Say ok"
    assert args.agent_backend == "claude-cli"
    assert args.agent_model == "haiku"
    assert args.agent_cwd == Path("/tmp")


def test_parser_accepts_doctor_command() -> None:
    args = build_parser().parse_args(
        [
            "doctor",
            "--env",
            ".env.example",
            "--agent-backend",
            "codex-app-server",
            "--agent-cwd",
            "/tmp",
        ]
    )

    assert args.command == "doctor"
    assert args.env == Path(".env.example")
    assert args.agent_backend == "codex-app-server"
    assert args.agent_cwd == Path("/tmp")


def test_doctor_fails_when_codex_command_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "LIVEKIT_URL=wss://example.livekit.cloud",
                f"LIVEKIT_API_KEY={TEST_LIVEKIT_KEY}",
                f"LIVEKIT_API_SECRET={TEST_LIVEKIT_HMAC}",
                f"DEEPGRAM_API_KEY={TEST_STT_KEY}",
                f"ELEVENLABS_API_KEY={TEST_TTS_KEY}",
                f"ELEVENLABS_VOICE_ID={TEST_TTS_VOICE}",
                f"ELEVENLABS_MODEL={TEST_TTS_MODEL}",
            ]
        ),
        encoding="utf-8",
    )
    for key in (
        "LIVEKIT_URL",
        "LIVEKIT_API_KEY",
        "LIVEKIT_API_SECRET",
        "DEEPGRAM_API_KEY",
        "ELEVENLABS_API_KEY",
        "ELEVENLABS_VOICE_ID",
        "ELEVENLABS_MODEL",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr("shutil.which", lambda command: None)
    monkeypatch.setattr(
        "sys.argv",
        [
            "line",
            "doctor",
            "--env",
            str(env_path),
            "--agent-backend",
            "codex-app-server",
            "--agent-cwd",
            str(tmp_path),
        ],
    )

    with pytest.raises(SystemExit) as error:
        main()

    assert error.value.code == 2
    captured = capsys.readouterr()
    assert "FAIL codex command" in captured.out
    assert "Doctor failed." in captured.out
    assert "Traceback" not in captured.err


def test_doctor_fails_when_env_contains_placeholders(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "LIVEKIT_URL=wss://your" "-project.livekit.cloud",
                "LIVEKIT_API_KEY=replace" "-me",
                "LIVEKIT_API_SECRET=replace" "-me",
                "DEEPGRAM_API_KEY=replace" "-me",
                "ELEVENLABS_API_KEY=replace" "-me",
                f"ELEVENLABS_VOICE_ID={TEST_TTS_VOICE}",
                f"ELEVENLABS_MODEL={TEST_TTS_MODEL}",
            ]
        ),
        encoding="utf-8",
    )
    for key in (
        "LIVEKIT_URL",
        "LIVEKIT_API_KEY",
        "LIVEKIT_API_SECRET",
        "DEEPGRAM_API_KEY",
        "ELEVENLABS_API_KEY",
        "ELEVENLABS_VOICE_ID",
        "ELEVENLABS_MODEL",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr("shutil.which", lambda command: f"/usr/local/bin/{command}")
    monkeypatch.setattr(
        "sys.argv",
        [
            "line",
            "doctor",
            "--env",
            str(env_path),
            "--agent-backend",
            "codex-app-server",
            "--agent-cwd",
            str(tmp_path),
        ],
    )

    with pytest.raises(SystemExit) as error:
        main()

    assert error.value.code == 2
    captured = capsys.readouterr()
    assert "FAIL voice env" in captured.out
    assert "placeholder values" in captured.out


def test_parser_accepts_codex_app_server_backend() -> None:
    args = build_parser().parse_args(
        [
            "agent-run",
            "Check tests",
            "--agent-backend",
            "codex-app-server",
            "--agent-model",
            "gpt-5.5",
            "--agent-cwd",
            "/tmp",
            "--agent-timeout",
            "120",
            "--codex-endpoint",
            "ws://127.0.0.1:4500",
            "--codex-thread-id",
            "thread-existing",
        ]
    )

    assert args.command == "agent-run"
    assert args.agent_backend == "codex-app-server"
    assert args.agent_model == "gpt-5.5"
    assert args.agent_cwd == Path("/tmp")
    assert args.agent_timeout == 120.0
    assert args.codex_endpoint == "ws://127.0.0.1:4500"
    assert args.codex_thread_id == "thread-existing"


def test_run_agent_once_closes_backend_after_reply() -> None:
    backend = ClosableFakeBackend()

    result = asyncio.run(run_agent_once(backend, "status"))

    assert result.reply == "done"
    assert backend.closed is True


class ClosableFakeBackend:
    def __init__(self) -> None:
        self.closed = False

    async def run(self, prompt: str) -> AgentJobResult:
        return AgentJobResult(
            prompt=prompt,
            reply="done",
            model="fake",
            stdout="done",
            stderr="",
        )

    async def aclose(self) -> None:
        self.closed = True
