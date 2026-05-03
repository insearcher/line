from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class AgentBackendError(RuntimeError):
    pass


DEFAULT_VOICE_SYSTEM_PROMPT = (
    "You are a voice coding agent for a user wearing headphones. "
    "Reply in English, briefly, and in a form suitable for speech: 1-3 short sentences. "
    "Do not use Markdown tables, long lists, code blocks, or unnecessary preambles. "
    "If the reply_to_voice tool is available, use it for any text that should be spoken. "
    "Pass only concise user-facing text to reply_to_voice, without intermediate reasoning or logs. "
    "Use status=\"ack\" when you accept a task and start working. "
    "For long-running work, use status=\"progress\" about every 3 minutes, only when there is useful new information. "
    "Use status=\"done\" for the final successful spoken result, or status=\"error\" when the task cannot be completed. "
    "Keep all reply_to_voice text short and suitable for immediate speech."
)

VOICE_REPLY_TOOL_NAME = "reply_to_voice"
VOICE_REPLY_STATUSES = ("ack", "progress", "done", "error", "reply")


@dataclass(frozen=True)
class VoiceReply:
    text: str
    status: str = "reply"


@dataclass(frozen=True)
class AgentJobResult:
    prompt: str
    reply: str
    model: str
    stdout: str
    stderr: str
    full_reply: str | None = None
    spoken_reply: str | None = None
    voice_replies: tuple[VoiceReply, ...] = ()


class AgentBackend(Protocol):
    @property
    def label(self) -> str: ...

    @property
    def model(self) -> str: ...

    async def run(self, prompt: str) -> AgentJobResult: ...
