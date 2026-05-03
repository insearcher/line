from __future__ import annotations

import asyncio

from line.speech_queue import SpeechQueue


def test_speech_queue_enqueue_does_not_wait_for_playout() -> None:
    async def run_case() -> None:
        publisher = SlowPublisher()
        queue = SpeechQueue(publisher)
        await queue.start()

        queue.enqueue("первое")
        queue.enqueue("второе")

        assert publisher.spoken == []
        publisher.release_next.set()
        await asyncio.sleep(0)
        await queue.join()

        assert publisher.spoken == ["первое", "второе"]
        await queue.aclose()

    asyncio.run(run_case())


def test_speech_queue_can_enqueue_tones_between_spoken_items() -> None:
    async def run_case() -> None:
        publisher = SlowPublisher()
        queue = SpeechQueue(publisher)
        await queue.start()

        queue.enqueue_tone("capture_start")
        queue.enqueue("готово")

        publisher.release_next.set()
        await asyncio.sleep(0)
        await queue.join()

        assert publisher.tones == ["capture_start"]
        assert publisher.spoken == ["готово"]
        await queue.aclose()

    asyncio.run(run_case())


class SlowPublisher:
    def __init__(self) -> None:
        self.spoken: list[str] = []
        self.tones: list[str] = []
        self.release_next = asyncio.Event()

    async def say(self, text: str) -> None:
        await self.release_next.wait()
        self.spoken.append(text)

    async def play_tone(self, cue: str) -> None:
        await self.release_next.wait()
        self.tones.append(cue)
