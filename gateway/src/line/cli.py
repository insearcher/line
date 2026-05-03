from __future__ import annotations

import argparse
import asyncio
from collections.abc import Callable
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import shutil
import sys

from line.agent_backend import (
    AgentBackendError,
    AgentJobResult,
    ClaudeCliBackend,
    ClaudeCliConfig,
    CodexAppServerBackend,
    CodexAppServerConfig,
)
from line.capture import CaptureConfig, CaptureMode
from line.cc_channel import CcChannelClient, CcChannelError
from line.demo_server import DemoServerConfig, run_demo_server
from line.livekit_worker import run_worker
from line.lowlevel_worker import LowLevelWorkerConfig, run_lowlevel_worker
from line.pairing import format_pairing_instructions, PairingStore
from line.routing_service import route_transcript
from line.settings import ConfigError, VoiceConfig, load_env_file
from line.task_queue import TaskQueue
from line.tokens import generate_join_token


DEFAULT_QUEUE_PATH = Path("data/line_tasks.jsonl")


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    ok: bool
    detail: str


def add_agent_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--agent-backend",
        choices=("router", "claude-cli", "codex-app-server"),
        default="router",
        help="Where recognized text should be dispatched.",
    )
    parser.add_argument("--agent-model", default="haiku", help="Model for the selected agent backend.")
    parser.add_argument("--agent-cwd", type=Path, default=None, help="Working directory for agent subprocess/backend.")
    parser.add_argument(
        "--codex-endpoint",
        default=None,
        help="Existing Codex app-server endpoint, for example ws://127.0.0.1:4500.",
    )
    parser.add_argument(
        "--codex-thread-id",
        default=None,
        help="Existing Codex thread id to resume before sending the first turn.",
    )
    parser.add_argument(
        "--agent-permission-mode",
        default=None,
        help="Optional Claude Code permission mode, for example acceptEdits or dontAsk.",
    )
    parser.add_argument("--agent-timeout", type=float, default=900.0, help="Agent subprocess timeout in seconds.")
    parser.add_argument(
        "--agent-max-budget-usd",
        type=float,
        default=None,
        help="Optional Claude CLI --max-budget-usd guardrail.",
    )


def add_capture_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--capture-mode",
        choices=tuple(mode.value for mode in CaptureMode),
        type=CaptureMode,
        default=CaptureMode.DIRECT,
        help="Use direct dispatch or wake-word marker capture.",
    )
    parser.add_argument("--capture-wake-word", default="", help="Optional wake word required before start phrase.")
    parser.add_argument("--capture-start", default="start command", help="Phrase that starts command capture.")
    parser.add_argument("--capture-submit", default="send command", help="Phrase that submits captured command.")
    parser.add_argument("--capture-cancel", default="cancel", help="Phrase that cancels captured command.")
    parser.add_argument(
        "--capture-silence-timeout",
        type=float,
        default=20.0,
        help="Seconds of silence before captured command is cancelled.",
    )


def run_dry_run(text: str, queue_path: Path = DEFAULT_QUEUE_PATH) -> str:
    queue = TaskQueue(queue_path)
    result = route_transcript(text=text, queue=queue)

    payload = {
        "intent": result.intent,
        "task_text": result.task.task_text if result.task else None,
        "spoken_reply": result.reply,
        "queued_task": asdict(result.task) if result.task else None,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="line")
    subparsers = parser.add_subparsers(dest="command", required=True)

    dry_run = subparsers.add_parser("dry-run", help="Classify text and optionally enqueue a fake Codex task.")
    dry_run.add_argument("text", help="Recognized user text to route.")
    dry_run.add_argument(
        "--queue",
        type=Path,
        default=DEFAULT_QUEUE_PATH,
        help="Path to JSONL task queue.",
    )
    dry_run.add_argument(
        "--env",
        type=Path,
        default=Path(".env"),
        help="Optional .env file to load before running.",
    )

    config_check = subparsers.add_parser("config-check", help="Verify LiveKit and Deepgram settings.")
    config_check.add_argument("--env", type=Path, default=Path(".env"), help="Optional .env file to load.")

    doctor = subparsers.add_parser("doctor", help="Check local setup for the source-built dev workflow.")
    doctor.add_argument("--env", type=Path, default=Path(".env"), help="Optional .env file to load.")
    add_agent_arguments(doctor)
    doctor.set_defaults(agent_backend="codex-app-server")

    worker = subparsers.add_parser("worker", help="Run the LiveKit voice worker.")
    worker.add_argument("--env", type=Path, default=Path(".env"), help="Optional .env file to load.")
    worker.add_argument("--queue", type=Path, default=DEFAULT_QUEUE_PATH, help="Path to JSONL task queue.")

    token = subparsers.add_parser("token", help="Generate a LiveKit room token for iPhone/browser testing.")
    token.add_argument("--env", type=Path, default=Path(".env"), help="Optional .env file to load.")
    token.add_argument("--room", default="line-dev", help="LiveKit room name.")
    token.add_argument("--identity", default="iphone", help="Participant identity.")

    demo_server = subparsers.add_parser("demo-server", help="Run the local browser dashboard server.")
    demo_server.add_argument("--env", type=Path, default=Path(".env"), help="Optional .env file to load.")
    demo_server.add_argument("--host", default="127.0.0.1", help="HTTP host.")
    demo_server.add_argument("--port", type=int, default=8787, help="HTTP port.")
    demo_server.add_argument("--room", default="line-dev", help="LiveKit room name.")
    demo_server.add_argument("--identity", default="mac-test", help="Browser participant identity.")
    demo_server.add_argument("--web-dir", type=Path, default=Path("web"), help="Static dashboard directory.")
    demo_server.add_argument("--events", type=Path, default=Path("data/events.jsonl"), help="Event log path.")
    demo_server.add_argument("--usage", type=Path, default=Path("data/usage.jsonl"), help="Usage log path.")
    demo_server.add_argument("--queue", type=Path, default=DEFAULT_QUEUE_PATH, help="Path to JSONL task queue.")
    demo_server.add_argument("--agent-runs", type=Path, default=Path("data/agent_runs.jsonl"), help="Agent run state path.")
    demo_server.add_argument("--control", type=Path, default=Path("data/control.jsonl"), help="Control event path.")
    demo_server.add_argument("--pairing-state", type=Path, default=Path("data/pairing_state.json"), help="Pairing state path.")

    pair = subparsers.add_parser("pair", help="Create a one-time iPhone pairing code for the demo server.")
    pair.add_argument("--server-url", required=True, help="Reachable demo server URL, for example http://100.x.y.z:8787.")
    pair.add_argument("--state", type=Path, default=Path("data/pairing_state.json"), help="Pairing state path.")
    pair.add_argument("--ttl", type=int, default=300, help="Pairing code lifetime in seconds.")

    lowlevel_worker = subparsers.add_parser(
        "lowlevel-worker",
        help="Run the low-level LiveKit participant worker with local VAD-gated STT.",
    )
    lowlevel_worker.add_argument("--env", type=Path, default=Path(".env"), help="Optional .env file to load.")
    lowlevel_worker.add_argument("--room", default="line-dev", help="LiveKit room name.")
    lowlevel_worker.add_argument("--identity", default="line-worker", help="Worker participant identity.")
    lowlevel_worker.add_argument("--events", type=Path, default=Path("data/events.jsonl"), help="Event log path.")
    lowlevel_worker.add_argument("--usage", type=Path, default=Path("data/usage.jsonl"), help="Usage log path.")
    lowlevel_worker.add_argument("--queue", type=Path, default=DEFAULT_QUEUE_PATH, help="Path to JSONL task queue.")
    lowlevel_worker.add_argument("--control", type=Path, default=Path("data/control.jsonl"), help="Control event path.")
    lowlevel_worker.add_argument(
        "--agent-runs",
        type=Path,
        default=Path("data/agent_runs.jsonl"),
        help="Path to JSONL agent run state.",
    )
    lowlevel_worker.add_argument(
        "--cc-channel-url",
        default=None,
        help="Optional local Claude Code Channels bridge URL, for example http://127.0.0.1:8790.",
    )
    lowlevel_worker.add_argument(
        "--cc-channel-token",
        default=None,
        help="Optional bearer token for the CC channel bridge.",
    )
    add_agent_arguments(lowlevel_worker)
    add_capture_arguments(lowlevel_worker)

    cc_send = subparsers.add_parser(
        "cc-channel-send",
        help="Send a text message into the local Claude Code Channels bridge.",
    )
    cc_send.add_argument("text", help="Text to send as a voice channel event.")
    cc_send.add_argument("--url", default="http://127.0.0.1:8790", help="CC channel bridge URL.")
    cc_send.add_argument("--token", default=None, help="Optional bearer token for the bridge.")
    cc_send.add_argument("--chat-id", default="voice", help="Voice chat id to attach to the event.")

    agent_run = subparsers.add_parser(
        "agent-run",
        help="Run a one-off text prompt through the configured agent backend.",
    )
    agent_run.add_argument("text", help="Text prompt to send to the agent backend.")
    add_agent_arguments(agent_run)
    return parser


async def run_agent_once(backend, text: str) -> AgentJobResult:
    try:
        return await backend.run(text)
    finally:
        aclose = getattr(backend, "aclose", None)
        if aclose is not None:
            await aclose()


def run_doctor(
    *,
    env_path: Path,
    agent_backend: str,
    agent_cwd: Path | None,
    command_lookup: Callable[[str], str | None] | None = None,
) -> tuple[DoctorCheck, ...]:
    checks: list[DoctorCheck] = []
    command_lookup = command_lookup or shutil.which

    python_version = ".".join(str(part) for part in sys.version_info[:3])
    checks.append(
        DoctorCheck(
            name="python",
            ok=sys.version_info >= (3, 12),
            detail=f"{python_version} (requires >=3.12)",
        )
    )

    if env_path.exists():
        load_env_file(env_path)
    else:
        checks.append(DoctorCheck(name="env file", ok=False, detail=f"{env_path} does not exist"))

    try:
        voice_config = VoiceConfig.from_env()
    except ConfigError as error:
        checks.append(DoctorCheck(name="voice env", ok=False, detail=str(error)))
    else:
        placeholder_keys = voice_config_placeholder_keys(voice_config)
        if placeholder_keys:
            checks.append(
                DoctorCheck(
                    name="voice env",
                    ok=False,
                    detail=f"placeholder values: {', '.join(placeholder_keys)}",
                )
            )
        else:
            checks.append(DoctorCheck(name="voice env", ok=True, detail="LiveKit, STT, and TTS settings are present"))

    cwd = agent_cwd or Path.cwd()
    checks.append(
        DoctorCheck(
            name="agent cwd",
            ok=cwd.exists() and cwd.is_dir(),
            detail=str(cwd),
        )
    )

    command_name = {"codex-app-server": "codex", "claude-cli": "claude"}.get(agent_backend)
    if command_name is None:
        checks.append(DoctorCheck(name="agent command", ok=True, detail=f"{agent_backend} does not require a CLI agent"))
    else:
        command_path = command_lookup(command_name)
        checks.append(
            DoctorCheck(
                name=f"{command_name} command",
                ok=command_path is not None,
                detail=command_path or f"{command_name} executable not found on PATH",
            )
        )

    return tuple(checks)


def voice_config_placeholder_keys(config: VoiceConfig) -> tuple[str, ...]:
    placeholder_values = {
        "replace" "-me",
        "change" "me",
        "change" "-me",
        "your" "-key",
    }
    candidates: dict[str, str | None] = {
        "LIVEKIT_URL": config.livekit_url,
        "LIVEKIT_API_KEY": config.livekit_api_key,
        "LIVEKIT_API_SECRET": config.livekit_api_secret,
        "DEEPGRAM_API_KEY": config.deepgram_api_key,
        "ELEVENLABS_API_KEY": config.elevenlabs_api_key if config.tts_provider == "elevenlabs" else None,
        "ELEVENLABS_VOICE_ID": config.elevenlabs_voice_id if config.tts_provider == "elevenlabs" else None,
        "ELEVENLABS_MODEL": config.elevenlabs_model if config.tts_provider == "elevenlabs" else None,
    }
    placeholder_keys = []
    for key, value in candidates.items():
        if value is None:
            continue
        normalized = value.strip().lower()
        if normalized in placeholder_values or "your" "-project" in normalized:
            placeholder_keys.append(key)
    return tuple(placeholder_keys)


def print_doctor_report(checks: tuple[DoctorCheck, ...]) -> bool:
    failed = False
    for check in checks:
        status = "OK" if check.ok else "FAIL"
        print(f"{status} {check.name}: {check.detail}")
        failed = failed or not check.ok
    print("Doctor failed." if failed else "Doctor passed.")
    return not failed


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "dry-run":
        load_env_file(args.env)
        print(run_dry_run(text=args.text, queue_path=args.queue))
    elif args.command == "config-check":
        load_env_file(args.env)
        try:
            VoiceConfig.from_env()
        except ConfigError as error:
            print(str(error), file=sys.stderr)
            raise SystemExit(2) from None
        print("Voice config ok.")
    elif args.command == "doctor":
        checks = run_doctor(env_path=args.env, agent_backend=args.agent_backend, agent_cwd=args.agent_cwd)
        if not print_doctor_report(checks):
            raise SystemExit(2)
    elif args.command == "worker":
        try:
            run_worker(env_path=args.env, queue_path=args.queue)
        except ConfigError as error:
            print(str(error), file=sys.stderr)
            raise SystemExit(2) from None
    elif args.command == "token":
        load_env_file(args.env)
        try:
            config = VoiceConfig.from_env()
        except ConfigError as error:
            print(str(error), file=sys.stderr)
            raise SystemExit(2) from None
        token_value = generate_join_token(config=config, room=args.room, identity=args.identity)
        print(f"LIVEKIT_URL={config.livekit_url}")
        print(f"LIVEKIT_ROOM={args.room}")
        print(f"LIVEKIT_TOKEN={token_value}")
    elif args.command == "demo-server":
        run_demo_server(
            DemoServerConfig(
                host=args.host,
                port=args.port,
                room=args.room,
                identity=args.identity,
                web_dir=args.web_dir,
                events_path=args.events,
                queue_path=args.queue,
                usage_path=args.usage,
                agent_runs_path=args.agent_runs,
                control_path=args.control,
                pairing_state_path=args.pairing_state,
                env_path=args.env,
            )
        )
    elif args.command == "pair":
        session = PairingStore(args.state).start_pairing(server_url=args.server_url, ttl_seconds=args.ttl)
        print(format_pairing_instructions(session))
    elif args.command == "lowlevel-worker":
        run_lowlevel_worker(
            LowLevelWorkerConfig(
                room=args.room,
                identity=args.identity,
                env_path=args.env,
                events_path=args.events,
                queue_path=args.queue,
                usage_path=args.usage,
                control_path=args.control,
                agent_runs_path=args.agent_runs,
                cc_channel_url=args.cc_channel_url,
                cc_channel_token=args.cc_channel_token,
                agent_backend=args.agent_backend,
                agent_model=args.agent_model,
                agent_cwd=args.agent_cwd,
                codex_endpoint=args.codex_endpoint,
                codex_thread_id=args.codex_thread_id,
                agent_permission_mode=args.agent_permission_mode,
                agent_timeout_seconds=args.agent_timeout,
                agent_max_budget_usd=args.agent_max_budget_usd,
                capture_config=CaptureConfig(
                    mode=args.capture_mode,
                    wake_word=args.capture_wake_word,
                    start_phrase=args.capture_start,
                    submit_phrase=args.capture_submit,
                    cancel_phrase=args.capture_cancel,
                    silence_timeout_seconds=args.capture_silence_timeout,
                ),
            )
        )
    elif args.command == "cc-channel-send":
        try:
            response = CcChannelClient(base_url=args.url, token=args.token).send_voice_message(
                args.text,
                chat_id=args.chat_id,
            )
        except CcChannelError as error:
            print(str(error), file=sys.stderr)
            raise SystemExit(2) from None
        print(json.dumps(response, ensure_ascii=False, indent=2, sort_keys=True))
    elif args.command == "agent-run":
        if args.agent_backend == "claude-cli":
            backend = ClaudeCliBackend(
                ClaudeCliConfig(
                    model=args.agent_model,
                    cwd=args.agent_cwd,
                    permission_mode=args.agent_permission_mode,
                    timeout_seconds=args.agent_timeout,
                    max_budget_usd=args.agent_max_budget_usd,
                )
            )
        elif args.agent_backend == "codex-app-server":
            backend = CodexAppServerBackend(
                CodexAppServerConfig(
                    endpoint=args.codex_endpoint,
                    thread_id=args.codex_thread_id,
                    cwd=args.agent_cwd,
                    model=None if args.agent_model == "haiku" else args.agent_model,
                    timeout_seconds=args.agent_timeout,
                )
            )
        else:
            print("agent-run requires --agent-backend claude-cli or codex-app-server", file=sys.stderr)
            raise SystemExit(2)
        try:
            result = asyncio.run(run_agent_once(backend, args.text))
        except AgentBackendError as error:
            print(str(error), file=sys.stderr)
            raise SystemExit(2) from None
        print(result.reply)
