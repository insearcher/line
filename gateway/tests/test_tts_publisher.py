from __future__ import annotations

import asyncio
from types import SimpleNamespace

from line.events import EventLog
from line.settings import VoiceConfig
from line.tts_publisher import TTSPublisher, build_tts_provider
from line.usage import UsageLog

TEST_LIVEKIT_HMAC = "0" * 32
TEST_LIVEKIT_KEY = "test-livekit-value"
TEST_STT_KEY = "test-stt-value"
TEST_TTS_KEY = "test-tts-value"
TEST_TTS_VOICE = "test-tts-voice"
TEST_TTS_MODEL = "test-tts-model"


def test_build_tts_provider_passes_owned_http_session_to_elevenlabs() -> None:
    session = object()
    config = VoiceConfig(
        livekit_url="wss://example.livekit.cloud",
        livekit_api_key=TEST_LIVEKIT_KEY,
        livekit_api_secret=TEST_LIVEKIT_HMAC,
        deepgram_api_key=TEST_STT_KEY,
        tts_language="en-US",
        tts_provider="elevenlabs",
        elevenlabs_api_key=TEST_TTS_KEY,
        elevenlabs_voice_id=TEST_TTS_VOICE,
        elevenlabs_model=TEST_TTS_MODEL,
    )

    tts = build_tts_provider(
        config=config,
        deepgram_module=FakeDeepgramModule,
        elevenlabs_module=FakeElevenLabsModule,
        http_session=session,
    )

    assert tts.kwargs["api_key"] == TEST_TTS_KEY
    assert tts.kwargs["voice_id"] == TEST_TTS_VOICE
    assert tts.kwargs["model"] == TEST_TTS_MODEL
    assert tts.kwargs["language"] == "en-US"
    assert tts.kwargs["http_session"] is session


def test_tts_publisher_publishes_track_and_captures_synthesized_frames(tmp_path) -> None:
    room = FakeRoom()
    tts = FakeTTS([FakeFrame(0.1), FakeFrame(0.2)])
    events = EventLog(tmp_path / "events.jsonl")
    usage = UsageLog(tmp_path / "usage.jsonl")
    publisher = TTSPublisher(
        room=room,
        rtc_module=FakeRTC,
        tts=tts,
        events=events,
        usage=usage,
        track_name="line_voice",
    )

    result = asyncio.run(_start_and_say(publisher, "Accepted the task."))

    assert room.local_participant.published_track.name == "line_voice"
    assert room.local_participant.published_options.source == FakeRTC.TrackSource.SOURCE_MICROPHONE
    assert [frame.duration for frame in publisher.audio_source.frames] == [0.1, 0.2]
    assert result.spoken is True
    assert result.audio_seconds == 0.3
    assert usage.monthly_summary(result.created_at[:7])["tts.chars"]["chars"] == len("Accepted the task.")
    assert usage.monthly_summary(result.created_at[:7])["tts.audio"]["seconds"] == 0.3
    assert [event.type for event in events.read_all()] == [
        "tts.track_published",
        "tts.speak_started",
        "tts.speak_finished",
    ]


def test_tts_publisher_records_provider_error_without_raising(tmp_path) -> None:
    publisher = TTSPublisher(
        room=FakeRoom(),
        rtc_module=FakeRTC,
        tts=FailingTTS(),
        events=EventLog(tmp_path / "events.jsonl"),
        usage=UsageLog(tmp_path / "usage.jsonl"),
    )

    result = asyncio.run(_start_and_say(publisher, "Accepted the task."))

    assert result.spoken is False
    assert [event.type for event in publisher.events.read_all()] == [
        "tts.track_published",
        "tts.speak_started",
        "tts.error",
    ]


def test_tts_publisher_generates_short_tone_without_tts_chars(tmp_path) -> None:
    publisher = TTSPublisher(
        room=FakeRoom(),
        rtc_module=FakeRTC,
        tts=FakeTTS([]),
        events=EventLog(tmp_path / "events.jsonl"),
        usage=UsageLog(tmp_path / "usage.jsonl"),
    )

    result = asyncio.run(_start_and_play_tone(publisher, "capture_submit"))

    assert result.spoken is True
    assert result.cue == "capture_submit"
    assert 0 < result.audio_seconds < 0.5
    assert publisher.audio_source.frames
    assert "tts.chars" not in publisher._usage.monthly_summary(result.created_at[:7])
    assert [event.type for event in publisher.events.read_all()] == [
        "tts.track_published",
        "tts.tone_started",
        "tts.tone_finished",
    ]


async def _start_and_say(publisher: TTSPublisher, text: str):
    await publisher.start()
    return await publisher.say(text)


async def _start_and_play_tone(publisher: TTSPublisher, cue: str):
    await publisher.start()
    return await publisher.play_tone(cue)


class FakeFrame:
    def __init__(
        self,
        duration: float | None = None,
        *,
        data: bytes = b"",
        sample_rate: int = 22050,
        num_channels: int = 1,
        samples_per_channel: int | None = None,
    ) -> None:
        if duration is None:
            duration = (samples_per_channel or 0) / sample_rate
        self.duration = duration
        self.data = data
        self.sample_rate = sample_rate
        self.num_channels = num_channels
        self.samples_per_channel = samples_per_channel


class FakeSynthesizedAudio:
    def __init__(self, frame: FakeFrame) -> None:
        self.frame = frame


class FakeChunkedStream:
    def __init__(self, frames: list[FakeFrame]) -> None:
        self._frames = frames

    async def __aenter__(self) -> FakeChunkedStream:
        return self

    async def __aexit__(self, exc_type, exc, exc_tb) -> None:
        return None

    def __aiter__(self):
        self._iter = iter(self._frames)
        return self

    async def __anext__(self) -> FakeSynthesizedAudio:
        try:
            return FakeSynthesizedAudio(next(self._iter))
        except StopIteration as error:
            raise StopAsyncIteration from error


class FakeTTS:
    sample_rate = 22050
    num_channels = 1

    def __init__(self, frames: list[FakeFrame]) -> None:
        self.frames = frames
        self.text = ""

    def synthesize(self, text: str) -> FakeChunkedStream:
        self.text = text
        return FakeChunkedStream(self.frames)


class FailingTTS(FakeTTS):
    def __init__(self) -> None:
        super().__init__([])

    def synthesize(self, text: str) -> FakeChunkedStream:
        del text
        raise RuntimeError("tts unavailable")


class FakeAudioSource:
    def __init__(self, sample_rate: int, num_channels: int, queue_size_ms: int = 1000) -> None:
        self.sample_rate = sample_rate
        self.num_channels = num_channels
        self.queue_size_ms = queue_size_ms
        self.frames: list[FakeFrame] = []
        self.closed = False

    async def capture_frame(self, frame: FakeFrame) -> None:
        self.frames.append(frame)

    async def wait_for_playout(self) -> None:
        return None

    async def aclose(self) -> None:
        self.closed = True


class FakeLocalAudioTrack:
    @staticmethod
    def create_audio_track(name: str, source: FakeAudioSource):
        return SimpleNamespace(name=name, source=source)


class FakeTrackPublishOptions:
    def __init__(self, source=None) -> None:
        self.source = source


class FakeTrackSource:
    SOURCE_MICROPHONE = 2


class FakeRTC:
    AudioSource = FakeAudioSource
    AudioFrame = FakeFrame
    LocalAudioTrack = FakeLocalAudioTrack
    TrackPublishOptions = FakeTrackPublishOptions
    TrackSource = FakeTrackSource


class FakeLocalParticipant:
    def __init__(self) -> None:
        self.published_track = None
        self.published_options = None

    async def publish_track(self, track, options):
        self.published_track = track
        self.published_options = options
        return SimpleNamespace(sid="TR_TTS")


class FakeRoom:
    def __init__(self) -> None:
        self.local_participant = FakeLocalParticipant()


class FakeElevenLabsModule:
    class TTS:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs


class FakeDeepgramModule:
    class TTS:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs
