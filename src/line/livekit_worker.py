from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any, AsyncIterable

from line.intent import IntentRouter
from line.routing_service import route_transcript
from line.settings import VoiceConfig, load_env_file
from line.task_queue import TaskQueue


class MissingVoiceDependencies(RuntimeError):
    pass


def run_worker(env_path: Path = Path(".env"), queue_path: Path = Path("data/line_tasks.jsonl")) -> None:
    load_env_file(env_path)
    config = VoiceConfig.from_env()

    try:
        from livekit.agents import AgentServer
    except ImportError as error:
        raise MissingVoiceDependencies(
            "Voice dependencies are not installed. Run: uv sync --extra voice"
        ) from error

    os.environ["LINE_ENV_PATH"] = str(env_path)
    os.environ["LINE_QUEUE_PATH"] = str(queue_path)
    server = AgentServer(
        ws_url=config.livekit_url,
        api_key=config.livekit_api_key,
        api_secret=config.livekit_api_secret,
    )
    server.rtc_session()(_livekit_entrypoint)

    asyncio.run(server.run(devmode=True))


async def _livekit_entrypoint(ctx: Any) -> None:
    try:
        from livekit.agents import AgentSession
        from livekit.plugins import deepgram, elevenlabs, silero
    except ImportError as error:
        raise MissingVoiceDependencies(
            "Voice dependencies are not installed. Run: uv sync --extra voice"
        ) from error

    env_path = Path(os.getenv("LINE_ENV_PATH") or ".env")
    queue_path = Path(os.getenv("LINE_QUEUE_PATH") or "data/line_tasks.jsonl")
    load_env_file(env_path)
    config = VoiceConfig.from_env()

    session = AgentSession(
        stt=deepgram.STT(
            api_key=config.deepgram_api_key,
            model="nova-3",
            language=config.deepgram_language,
        ),
        tts=_build_tts(config=config, deepgram=deepgram, elevenlabs=elevenlabs),
        vad=silero.VAD.load(),
    )
    agent = CodexRouterAgent(router=IntentRouter(), queue=TaskQueue(queue_path))
    await session.start(agent=agent, room=ctx.room)


def _build_tts(config: VoiceConfig, deepgram: Any, elevenlabs: Any) -> Any:
    if config.tts_provider == "deepgram":
        return deepgram.TTS(api_key=config.deepgram_api_key)

    if config.tts_provider == "elevenlabs":
        return elevenlabs.TTS(
            api_key=config.elevenlabs_api_key,
            voice_id=config.elevenlabs_voice_id,
            model=config.elevenlabs_model,
            language="ru",
        )

    raise RuntimeError(f"Unsupported TTS_PROVIDER: {config.tts_provider}")


class CodexRouterAgent:
    def __new__(cls, *args: Any, **kwargs: Any) -> Any:
        try:
            from livekit.agents import Agent
        except ImportError as error:
            raise MissingVoiceDependencies(
                "Voice dependencies are not installed. Run: uv sync --extra voice"
            ) from error

        class _Agent(Agent):
            def __init__(self, router: IntentRouter, queue: TaskQueue) -> None:
                super().__init__(
                    instructions=(
                        "You are a thin voice router for Codex. "
                        "Do not invent work. Route the user's final transcript through local rules "
                        "and reply with the exact short confirmation returned by the router."
                    )
                )
                self._router = router
                self._queue = queue
                self._latest_user_text = ""

            async def on_user_turn_completed(self, turn_ctx: Any, new_message: Any) -> None:
                self._latest_user_text = _message_text(new_message)
                reply = _route_text(
                    router=self._router,
                    queue=self._queue,
                    text=self._latest_user_text,
                )
                print(
                    f"line routed text={self._latest_user_text!r} reply={reply!r}",
                    flush=True,
                )
                self.session.say(reply)

                from livekit.agents import StopResponse

                raise StopResponse()

            async def llm_node(
                self,
                chat_ctx: Any,
                tools: list[Any],
                model_settings: Any,
            ) -> AsyncIterable[str]:
                text = self._latest_user_text or _chat_context_latest_text(chat_ctx)
                yield _route_text(router=self._router, queue=self._queue, text=text)

        return _Agent(*args, **kwargs)


def _route_text(router: IntentRouter, queue: TaskQueue, text: str) -> str:
    del router
    return route_transcript(text=text, queue=queue).reply


def _message_text(message: Any) -> str:
    text_content = getattr(message, "text_content", None)
    if isinstance(text_content, str):
        return text_content

    content = getattr(message, "content", None)
    if isinstance(content, list):
        return " ".join(item for item in content if isinstance(item, str))

    return ""


def _chat_context_latest_text(chat_ctx: Any) -> str:
    items = getattr(chat_ctx, "items", None) or getattr(chat_ctx, "messages", None) or []
    for item in reversed(list(items)):
        role = getattr(item, "role", "")
        if role != "user":
            continue
        text = _message_text(item)
        if text:
            return text
    return ""
