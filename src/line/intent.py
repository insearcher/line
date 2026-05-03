from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re


class IntentKind(StrEnum):
    CANCEL = "cancel"
    STATUS = "status"
    DISPATCH = "dispatch"
    CHAT = "chat"


@dataclass(frozen=True)
class Intent:
    kind: IntentKind
    original_text: str
    normalized_text: str
    spoken_reply: str
    task_text: str | None = None

    @property
    def should_enqueue(self) -> bool:
        return self.kind == IntentKind.DISPATCH and bool(self.task_text)


class IntentRouter:
    def __init__(self) -> None:
        self._cancel_patterns = (
            "cancel",
            "stop",
            "do not send",
            "don't send",
        )
        self._status_patterns = (
            "status",
            "what is happening",
            "how is the task",
            "progress",
        )
        self._dispatch_patterns = (
            r"^(?:ask|tell)\s+codex\s+(?:to\s+)?(.+)$",
            r"^send\s+(?:to\s+)?codex\s+(.+)$",
            r"^task\s+for\s+codex\s+(.+)$",
        )

    def classify(self, text: str) -> Intent:
        original_text = text.strip()
        normalized_text = self._normalize(original_text)

        if self._contains_any(normalized_text, self._cancel_patterns):
            return Intent(
                kind=IntentKind.CANCEL,
                original_text=original_text,
                normalized_text=normalized_text,
                spoken_reply="Okay, cancelled. Nothing was sent to Codex.",
            )

        if self._contains_any(normalized_text, self._status_patterns):
            return Intent(
                kind=IntentKind.STATUS,
                original_text=original_text,
                normalized_text=normalized_text,
                spoken_reply="Checking Codex queue status.",
            )

        task_text = self._extract_dispatch_task(normalized_text)
        if task_text:
            return Intent(
                kind=IntentKind.DISPATCH,
                original_text=original_text,
                normalized_text=normalized_text,
                task_text=task_text,
                spoken_reply=f"Accepted, sent Codex task: {task_text}.",
            )

        return Intent(
            kind=IntentKind.CHAT,
            original_text=original_text,
            normalized_text=normalized_text,
            spoken_reply="I can hear you. To send a task, say: ask Codex ...",
        )

    def _extract_dispatch_task(self, normalized_text: str) -> str | None:
        for pattern in self._dispatch_patterns:
            match = re.match(pattern, normalized_text, flags=re.IGNORECASE)
            if not match:
                continue
            task_text = match.group(1).strip(" .,:;!?")
            return task_text or None
        return None

    @staticmethod
    def _contains_any(text: str, patterns: tuple[str, ...]) -> bool:
        return any(pattern in text for pattern in patterns)

    @staticmethod
    def _normalize(text: str) -> str:
        lowered = text.lower()
        collapsed = re.sub(r"\s+", " ", lowered).strip()
        return collapsed.strip(" .,:;!?")
