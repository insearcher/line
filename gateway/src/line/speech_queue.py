from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class SpeechQueueItemKind(StrEnum):
    TEXT = "text"
    TONE = "tone"


@dataclass(frozen=True)
class SpeechQueueItem:
    kind: SpeechQueueItemKind
    value: str


class SpeechQueue:
    def __init__(self, publisher: Any) -> None:
        self._publisher = publisher
        self._queue: asyncio.Queue[SpeechQueueItem | None] = asyncio.Queue()
        self._worker: asyncio.Task | None = None

    async def start(self) -> None:
        if self._worker is not None:
            return
        self._worker = asyncio.create_task(self._run())

    def enqueue(self, text: str) -> None:
        clean_text = text.strip()
        if clean_text:
            self._queue.put_nowait(SpeechQueueItem(SpeechQueueItemKind.TEXT, clean_text))

    def enqueue_tone(self, cue: str) -> None:
        clean_cue = cue.strip()
        if clean_cue:
            self._queue.put_nowait(SpeechQueueItem(SpeechQueueItemKind.TONE, clean_cue))

    async def join(self) -> None:
        await self._queue.join()

    async def aclose(self) -> None:
        if self._worker is None:
            return
        self._queue.put_nowait(None)
        await self._worker
        self._worker = None

    async def _run(self) -> None:
        while True:
            item = await self._queue.get()
            try:
                if item is None:
                    return
                if item.kind == SpeechQueueItemKind.TEXT:
                    await self._publisher.say(item.value)
                elif item.kind == SpeechQueueItemKind.TONE:
                    await self._publisher.play_tone(item.value)
            finally:
                self._queue.task_done()
