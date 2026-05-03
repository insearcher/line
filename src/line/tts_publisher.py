from __future__ import annotations

import asyncio
from array import array
import math
from dataclasses import dataclass
from typing import Any

from line.events import EventLog
from line.settings import VoiceConfig
from line.time_utils import utc_now_iso
from line.usage import UsageLog


@dataclass(frozen=True)
class SpeechPublishResult:
    created_at: str
    text: str
    spoken: bool
    audio_seconds: float = 0.0
    error: str | None = None


@dataclass(frozen=True)
class TonePublishResult:
    created_at: str
    cue: str
    spoken: bool
    audio_seconds: float = 0.0
    error: str | None = None


@dataclass(frozen=True)
class ToneSpec:
    frequencies: tuple[float, ...]
    segment_seconds: float
    amplitude: float


class TTSPublisher:
    def __init__(
        self,
        *,
        room: Any,
        rtc_module: Any,
        tts: Any,
        events: EventLog,
        usage: UsageLog,
        track_name: str = "line_voice",
        queue_size_ms: int = 1000,
    ) -> None:
        self._room = room
        self._rtc = rtc_module
        self._tts = tts
        self.events = events
        self._usage = usage
        self._track_name = track_name
        self._queue_size_ms = queue_size_ms
        self._lock = asyncio.Lock()
        self._audio_source: Any | None = None
        self._publication: Any | None = None

    @property
    def audio_source(self) -> Any:
        if self._audio_source is None:
            raise RuntimeError("TTS publisher has not been started")
        return self._audio_source

    async def start(self) -> None:
        if self._audio_source is not None:
            return

        self._audio_source = self._rtc.AudioSource(
            self._tts.sample_rate,
            self._tts.num_channels,
            queue_size_ms=self._queue_size_ms,
        )
        track = self._rtc.LocalAudioTrack.create_audio_track(self._track_name, self._audio_source)
        options = self._rtc.TrackPublishOptions(source=self._rtc.TrackSource.SOURCE_MICROPHONE)
        self._publication = await self._room.local_participant.publish_track(track, options)
        self.events.append(
            "tts.track_published",
            {
                "track": getattr(self._publication, "sid", ""),
                "name": self._track_name,
                "sample_rate": self._tts.sample_rate,
                "num_channels": self._tts.num_channels,
            },
        )

    async def say(self, text: str) -> SpeechPublishResult:
        clean_text = text.strip()
        created_at = utc_now_iso()
        if not clean_text:
            return SpeechPublishResult(created_at=created_at, text="", spoken=False)

        async with self._lock:
            self._usage.record_chars("tts.chars", len(clean_text), created_at=created_at)
            self.events.append(
                "tts.speak_started",
                {"text": clean_text, "chars": len(clean_text)},
                created_at=created_at,
            )
            try:
                audio_seconds = await self._synthesize_and_capture(clean_text)
            except Exception as error:  # noqa: BLE001 - provider boundary
                formatted = format_error(error)
                self.events.append(
                    "tts.error",
                    {"text": clean_text, "error": formatted},
                    created_at=created_at,
                )
                return SpeechPublishResult(
                    created_at=created_at,
                    text=clean_text,
                    spoken=False,
                    error=formatted,
                )

            rounded_seconds = round(audio_seconds, 3)
            self._usage.record_seconds("tts.audio", rounded_seconds, created_at=created_at)
            self.events.append(
                "tts.speak_finished",
                {"text": clean_text, "seconds": rounded_seconds},
                created_at=created_at,
            )
            return SpeechPublishResult(
                created_at=created_at,
                text=clean_text,
                spoken=True,
                audio_seconds=rounded_seconds,
            )

    async def play_tone(self, cue: str) -> TonePublishResult:
        clean_cue = cue.strip()
        created_at = utc_now_iso()
        if not clean_cue:
            return TonePublishResult(created_at=created_at, cue="", spoken=False)

        async with self._lock:
            self.events.append("tts.tone_started", {"cue": clean_cue}, created_at=created_at)
            try:
                audio_seconds = await self._capture_tone(clean_cue)
            except Exception as error:  # noqa: BLE001 - provider boundary
                formatted = format_error(error)
                self.events.append(
                    "tts.tone_error",
                    {"cue": clean_cue, "error": formatted},
                    created_at=created_at,
                )
                return TonePublishResult(
                    created_at=created_at,
                    cue=clean_cue,
                    spoken=False,
                    error=formatted,
                )

            rounded_seconds = round(audio_seconds, 3)
            self._usage.record_seconds("tts.tone_audio", rounded_seconds, created_at=created_at)
            self.events.append(
                "tts.tone_finished",
                {"cue": clean_cue, "seconds": rounded_seconds},
                created_at=created_at,
            )
            return TonePublishResult(
                created_at=created_at,
                cue=clean_cue,
                spoken=True,
                audio_seconds=rounded_seconds,
            )

    async def aclose(self) -> None:
        if self._audio_source is not None:
            await self._audio_source.aclose()
            self._audio_source = None
        aclose = getattr(self._tts, "aclose", None)
        if aclose is not None:
            result = aclose()
            if asyncio.iscoroutine(result):
                await result

    async def _synthesize_and_capture(self, text: str) -> float:
        source = self.audio_source
        audio_seconds = 0.0
        async with self._tts.synthesize(text) as stream:
            async for synthesized_audio in stream:
                frame = synthesized_audio.frame
                audio_seconds += float(getattr(frame, "duration", 0.0))
                await source.capture_frame(frame)
        await source.wait_for_playout()
        return audio_seconds

    async def _capture_tone(self, cue: str) -> float:
        source = self.audio_source
        sample_rate = int(self._tts.sample_rate)
        num_channels = int(self._tts.num_channels)
        spec = tone_spec(cue)
        frame = self._build_tone_frame(
            frequencies=spec.frequencies,
            segment_seconds=spec.segment_seconds,
            amplitude=spec.amplitude,
            sample_rate=sample_rate,
            num_channels=num_channels,
        )
        await source.capture_frame(frame)
        await source.wait_for_playout()
        duration = getattr(frame, "duration", None)
        if duration is not None:
            return float(duration)
        return len(frame.data) / (sample_rate * num_channels * 2)

    def _build_tone_frame(
        self,
        *,
        frequencies: tuple[float, ...],
        segment_seconds: float,
        amplitude: float,
        sample_rate: int,
        num_channels: int,
    ) -> Any:
        samples_per_segment = max(1, int(sample_rate * segment_seconds))
        mono = array("h")
        for frequency in frequencies:
            for index in range(samples_per_segment):
                envelope = _tone_envelope(index=index, total=samples_per_segment)
                sample = int(32767 * amplitude * envelope * math.sin(2 * math.pi * frequency * index / sample_rate))
                mono.append(sample)
        if num_channels == 1:
            pcm = mono
        else:
            pcm = array("h")
            for sample in mono:
                pcm.extend([sample] * num_channels)
        return self._rtc.AudioFrame(
            data=pcm.tobytes(),
            sample_rate=sample_rate,
            num_channels=num_channels,
            samples_per_channel=len(mono),
        )


def tone_spec(cue: str) -> ToneSpec:
    if cue == "capture_start":
        return ToneSpec(frequencies=(660.0, 880.0), segment_seconds=0.075, amplitude=0.11)
    if cue == "capture_submit":
        return ToneSpec(frequencies=(988.0, 740.0), segment_seconds=0.08, amplitude=0.12)
    if cue == "capture_cancel":
        return ToneSpec(frequencies=(392.0, 330.0), segment_seconds=0.09, amplitude=0.11)
    return ToneSpec(frequencies=(784.0,), segment_seconds=0.12, amplitude=0.1)


def _tone_envelope(*, index: int, total: int) -> float:
    if total <= 1:
        return 1.0
    edge = max(1, int(total * 0.12))
    if index < edge:
        return index / edge
    if index >= total - edge:
        return (total - index - 1) / edge
    return 1.0


def build_tts_provider(
    *,
    config: VoiceConfig,
    deepgram_module: Any,
    elevenlabs_module: Any,
    http_session: Any,
) -> Any:
    if config.tts_provider == "deepgram":
        return deepgram_module.TTS(
            api_key=config.deepgram_api_key,
            http_session=http_session,
        )

    if config.tts_provider == "elevenlabs":
        return elevenlabs_module.TTS(
            api_key=config.elevenlabs_api_key,
            voice_id=config.elevenlabs_voice_id,
            model=config.elevenlabs_model,
            language="ru",
            http_session=http_session,
        )

    raise RuntimeError(f"Unsupported TTS_PROVIDER: {config.tts_provider}")


def format_error(error: Exception) -> str:
    message = str(error).strip()
    if len(message) > 500:
        message = f"{message[:497]}..."
    return f"{error.__class__.__name__}: {message}" if message else error.__class__.__name__
