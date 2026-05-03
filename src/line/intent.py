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
            "отмена",
            "отмени",
            "стоп",
            "не отправляй",
            "cancel",
            "stop",
        )
        self._status_patterns = (
            "статус",
            "что там",
            "как дела с задач",
            "status",
            "progress",
        )
        self._dispatch_patterns = (
            r"^(?:попроси|попросить)\s+codex\s+(.+)$",
            r"^(?:попроси|попросить)\s+кодекс\s+(.+)$",
            r"^(?:отправь|отправить)\s+(?:в\s+)?codex\s+(.+)$",
            r"^(?:отправь|отправить)\s+(?:в\s+)?кодекс\s+(.+)$",
            r"^(?:передай|передать)\s+(?:в\s+)?codex\s+(.+)$",
            r"^(?:передай|передать)\s+(?:в\s+)?кодекс\s+(.+)$",
            r"^задача\s+для\s+(?:codex|кодекса)\s+(.+)$",
        )

    def classify(self, text: str) -> Intent:
        original_text = text.strip()
        normalized_text = self._normalize(original_text)

        if self._contains_any(normalized_text, self._cancel_patterns):
            return Intent(
                kind=IntentKind.CANCEL,
                original_text=original_text,
                normalized_text=normalized_text,
                spoken_reply="Окей, отменил. В Codex ничего не отправляю.",
            )

        if self._contains_any(normalized_text, self._status_patterns):
            return Intent(
                kind=IntentKind.STATUS,
                original_text=original_text,
                normalized_text=normalized_text,
                spoken_reply="Проверяю статус очереди Codex.",
            )

        task_text = self._extract_dispatch_task(normalized_text)
        if task_text:
            return Intent(
                kind=IntentKind.DISPATCH,
                original_text=original_text,
                normalized_text=normalized_text,
                task_text=task_text,
                spoken_reply=f"Принял, отправил Codex задачу: {task_text}.",
            )

        return Intent(
            kind=IntentKind.CHAT,
            original_text=original_text,
            normalized_text=normalized_text,
            spoken_reply="Слышу тебя. Для отправки задачи скажи: попроси Codex ...",
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
        lowered = text.lower().replace("ё", "е")
        collapsed = re.sub(r"\s+", " ", lowered).strip()
        return collapsed.strip(" .,:;!?")
