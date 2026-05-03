from __future__ import annotations

import asyncio
from types import SimpleNamespace

from line.events import EventLog
from line import lowlevel_worker
from line.agent_backend import AgentJobResult, VoiceReply
from line.agent_runs import AgentRunStatus, AgentRunStore
from line.capture import CaptureConfig, CaptureMode, MarkerCaptureSession
from line.claude_channel import ClaudeReply
from line.task_queue import TaskQueue
from line.usage import UsageLog


def test_recognize_and_route_speech_records_usage_and_queues_task(tmp_path) -> None:
    frames = [SimpleNamespace(duration=1.25), SimpleNamespace(duration=0.75)]
    stt = FakeSTT("Ask Codex to check the queue")
    queue = TaskQueue(tmp_path / "tasks.jsonl")
    events = EventLog(tmp_path / "events.jsonl")
    runs = AgentRunStore(tmp_path / "agent_runs.jsonl")
    usage = UsageLog(tmp_path / "usage.jsonl")

    result = asyncio.run(
        lowlevel_worker.recognize_and_route_speech(
            frames=frames,
            stt=stt,
            queue=queue,
            events=events,
            usage=usage,
        )
    )

    assert stt.frames == frames
    assert result.transcript == "Ask Codex to check the queue"
    assert result.reply == "Accepted, sent Codex task: check the queue."
    assert queue.list_tasks()[0].task_text == "check the queue"
    assert usage.monthly_summary(result.created_at[:7])["vad.speech"]["seconds"] == 2.0
    assert usage.monthly_summary(result.created_at[:7])["stt.audio"]["seconds"] == 2.0
    assert [event.type for event in events.read_all()] == [
        "vad.speech",
        "stt.result",
        "transcript.final",
        "route.result",
        "task.queued",
    ]


def test_recognize_and_route_speech_speaks_route_reply(tmp_path) -> None:
    speaker = FakeSpeaker()

    result = asyncio.run(
        lowlevel_worker.recognize_and_route_speech(
            frames=[SimpleNamespace(duration=0.5)],
            stt=FakeSTT("status"),
            queue=TaskQueue(tmp_path / "tasks.jsonl"),
            events=EventLog(tmp_path / "events.jsonl"),
            usage=UsageLog(tmp_path / "usage.jsonl"),
            tts_publisher=speaker,
        )
    )

    assert result.reply == "Codex queue is empty."
    assert speaker.spoken_texts == ["Codex queue is empty."]


def test_recognize_and_route_speech_sends_transcript_to_claude_channel(tmp_path) -> None:
    client = FakeClaudeChannelClient()
    queue = TaskQueue(tmp_path / "tasks.jsonl")
    events = EventLog(tmp_path / "events.jsonl")

    result = asyncio.run(
        lowlevel_worker.recognize_and_route_speech(
            frames=[SimpleNamespace(duration=0.5)],
            stt=FakeSTT("Ask Claude to check tests"),
            queue=queue,
            events=events,
            usage=UsageLog(tmp_path / "usage.jsonl"),
            claude_channel_client=client,
        )
    )

    assert result.transcript == "Ask Claude to check tests"
    assert result.reply == ""
    assert result.route is None
    assert client.sent == [("Ask Claude to check tests", "voice")]
    assert queue.list_tasks() == []
    assert [event.type for event in events.read_all()] == [
        "vad.speech",
        "stt.result",
        "claude_channel.sent",
    ]


def test_recognize_and_route_speech_dispatches_to_agent_backend(tmp_path) -> None:
    speaker = FakeSpeechQueue()
    backend = FakeAgentBackend(reply="Haiku replied.")
    agent_tasks: set[asyncio.Task] = set()
    queue = TaskQueue(tmp_path / "tasks.jsonl")
    events = EventLog(tmp_path / "events.jsonl")
    runs = AgentRunStore(tmp_path / "agent_runs.jsonl")

    async def run_case():
        result = await lowlevel_worker.recognize_and_route_speech(
            frames=[SimpleNamespace(duration=0.5)],
            stt=FakeSTT("check tests"),
            queue=queue,
            events=events,
            usage=UsageLog(tmp_path / "usage.jsonl"),
            tts_publisher=speaker,
            agent_backend=backend,
            agent_runs=runs,
            agent_tasks=agent_tasks,
        )
        await asyncio.gather(*agent_tasks)
        return result

    result = asyncio.run(run_case())

    assert result.reply == "Accepted, sent haiku: check tests."
    assert result.route is None
    assert backend.prompts == ["check tests"]
    assert speaker.enqueued_texts == [
        "Accepted, sent haiku: check tests.",
        "Haiku replied.",
    ]
    assert queue.list_tasks() == []
    run = runs.list_runs()[0]
    assert run.status == AgentRunStatus.DONE
    assert run.backend == "haiku"
    assert run.model == "haiku"
    assert run.prompt == "check tests"
    assert run.reply == "Haiku replied."
    assert run.duration_seconds is not None
    assert [event.type for event in events.read_all()] == [
        "vad.speech",
        "stt.result",
        "agent_backend.dispatched",
        "agent_backend.running",
        "agent_backend.done",
    ]


def test_run_agent_backend_job_records_voice_reply_tool_payload(tmp_path) -> None:
    speaker = FakeSpeaker()
    events = EventLog(tmp_path / "events.jsonl")
    runs = AgentRunStore(tmp_path / "agent_runs.jsonl")
    run = runs.create_queued(backend="codex", model="gpt-5.5", prompt="where is the project?")
    backend = FakeAgentBackend(
        reply="The project is in the MVP folder.",
        voice_replies=(VoiceReply(text="The project is in the MVP folder.", status="done"),),
        full_reply="I am checking the project now.\n\nThe project is in the MVP folder.",
    )

    asyncio.run(
        lowlevel_worker.run_agent_backend_job(
            agent_backend=backend,
            prompt="where is the project?",
            tts_publisher=speaker,
            events=events,
            agent_runs=runs,
            run=run,
        )
    )

    assert speaker.spoken_texts == ["The project is in the MVP folder."]
    done_event = events.read_all()[-1]
    assert done_event.type == "agent_backend.done"
    assert done_event.payload["reply"] == "The project is in the MVP folder."
    assert done_event.payload["full_reply"] == "I am checking the project now.\n\nThe project is in the MVP folder."
    assert done_event.payload["voice_replies"] == [
        {"text": "The project is in the MVP folder.", "status": "done"}
    ]
    assert runs.list_runs()[0].reply == "The project is in the MVP folder."


def test_recognize_and_route_speech_marker_mode_buffers_until_submit(tmp_path) -> None:
    speaker = FakeSpeechQueue()
    backend = FakeAgentBackend(reply="done")
    capture_session = MarkerCaptureSession(CaptureConfig(mode=CaptureMode.MARKERS))
    agent_tasks: set[asyncio.Task] = set()
    queue = TaskQueue(tmp_path / "tasks.jsonl")
    events = EventLog(tmp_path / "events.jsonl")
    runs = AgentRunStore(tmp_path / "agent_runs.jsonl")

    async def run_case() -> None:
        await lowlevel_worker.recognize_and_route_speech(
            frames=[SimpleNamespace(duration=0.2)],
            stt=FakeSTT("start command"),
            queue=queue,
            events=events,
            usage=UsageLog(tmp_path / "usage.jsonl"),
            tts_publisher=speaker,
            agent_backend=backend,
            agent_runs=runs,
            agent_tasks=agent_tasks,
            capture_session=capture_session,
        )
        await lowlevel_worker.recognize_and_route_speech(
            frames=[SimpleNamespace(duration=0.2)],
            stt=FakeSTT("check tests"),
            queue=queue,
            events=events,
            usage=UsageLog(tmp_path / "usage.jsonl"),
            tts_publisher=speaker,
            agent_backend=backend,
            agent_runs=runs,
            agent_tasks=agent_tasks,
            capture_session=capture_session,
        )
        await lowlevel_worker.recognize_and_route_speech(
            frames=[SimpleNamespace(duration=0.2)],
            stt=FakeSTT("send command"),
            queue=queue,
            events=events,
            usage=UsageLog(tmp_path / "usage.jsonl"),
            tts_publisher=speaker,
            agent_backend=backend,
            agent_runs=runs,
            agent_tasks=agent_tasks,
            capture_session=capture_session,
        )
        await asyncio.gather(*agent_tasks)

    asyncio.run(run_case())

    assert backend.prompts == ["check tests"]
    assert speaker.enqueued_tones == ["capture_start", "capture_submit"]
    assert speaker.enqueued_texts == ["done"]
    assert [event.type for event in events.read_all() if event.type.startswith("capture.")] == [
        "capture.started",
        "capture.buffered",
        "capture.submitted",
    ]


def test_marker_mode_ignores_prompt_text_spoken_before_start_tone(tmp_path) -> None:
    speaker = FakeSpeechQueue()
    backend = FakeAgentBackend(reply="done")
    capture_session = MarkerCaptureSession(CaptureConfig(mode=CaptureMode.MARKERS))
    agent_tasks: set[asyncio.Task] = set()
    queue = TaskQueue(tmp_path / "tasks.jsonl")
    events = EventLog(tmp_path / "events.jsonl")
    runs = AgentRunStore(tmp_path / "agent_runs.jsonl")

    async def run_case() -> None:
        await lowlevel_worker.recognize_and_route_speech(
            frames=[SimpleNamespace(duration=0.2)],
            stt=FakeSTT("start command check tests send command"),
            queue=queue,
            events=events,
            usage=UsageLog(tmp_path / "usage.jsonl"),
            tts_publisher=speaker,
            agent_backend=backend,
            agent_runs=runs,
            agent_tasks=agent_tasks,
            capture_session=capture_session,
        )

    asyncio.run(run_case())

    assert backend.prompts == []
    assert speaker.enqueued_tones == ["capture_start"]
    assert speaker.enqueued_texts == []
    assert capture_session.is_capturing is True


def test_rolling_marker_probe_uses_overlapping_audio_window() -> None:
    probe = lowlevel_worker.RollingMarkerProbe(
        lowlevel_worker.MarkerProbeConfig(
            window_seconds=3.0,
            min_audio_seconds=1.0,
            interval_seconds=2.0,
        )
    )
    frame_1 = SimpleNamespace(duration=0.6)
    frame_2 = SimpleNamespace(duration=0.6)
    frame_3 = SimpleNamespace(duration=2.4)

    probe.add_frames([frame_1])
    assert probe.snapshot_if_due(now=10.0) is None

    first_snapshot = probe.add_frames([frame_2]).snapshot_if_due(now=10.1)
    assert first_snapshot == [frame_1, frame_2]
    assert probe.snapshot_if_due(now=11.0) is None

    second_snapshot = probe.add_frames([frame_3]).snapshot_if_due(now=12.2)
    assert second_snapshot == [frame_2, frame_3]


def test_marker_probe_starts_capture_before_regular_vad_end(tmp_path) -> None:
    speaker = FakeSpeechQueue()
    capture_session = MarkerCaptureSession(CaptureConfig(mode=CaptureMode.MARKERS))
    events = EventLog(tmp_path / "events.jsonl")

    async def run_case() -> bool:
        return await lowlevel_worker.probe_for_capture_start(
            frames=[SimpleNamespace(duration=1.0)],
            stt=FakeSTT("background words start command"),
            capture_session=capture_session,
            events=events,
            usage=UsageLog(tmp_path / "usage.jsonl"),
            tts_publisher=speaker,
            now=10.0,
        )

    started = asyncio.run(run_case())

    assert started is True
    assert capture_session.is_capturing is True
    assert capture_session.deadline == 30.0
    assert speaker.enqueued_tones == ["capture_start"]
    assert [event.type for event in events.read_all()] == [
        "marker_probe.started",
        "marker_probe.result",
        "capture.started",
    ]


def test_marker_probe_ignores_non_marker_transcript(tmp_path) -> None:
    speaker = FakeSpeechQueue()
    capture_session = MarkerCaptureSession(CaptureConfig(mode=CaptureMode.MARKERS))
    events = EventLog(tmp_path / "events.jsonl")

    async def run_case() -> bool:
        return await lowlevel_worker.probe_for_capture_start(
            frames=[SimpleNamespace(duration=1.0)],
            stt=FakeSTT("just background speech"),
            capture_session=capture_session,
            events=events,
            usage=UsageLog(tmp_path / "usage.jsonl"),
            tts_publisher=speaker,
            now=10.0,
        )

    started = asyncio.run(run_case())

    assert started is False
    assert capture_session.is_capturing is False
    assert speaker.enqueued_tones == []
    assert [event.type for event in events.read_all()] == [
        "marker_probe.started",
        "marker_probe.result",
    ]


def test_marker_probe_ignores_active_capture_text_without_cancel(tmp_path) -> None:
    speaker = FakeSpeechQueue()
    capture_session = MarkerCaptureSession(CaptureConfig(mode=CaptureMode.MARKERS))
    capture_session.handle_text("start command", now=9.0)
    capture_session.mark_ready(now=9.5)
    events = EventLog(tmp_path / "events.jsonl")

    async def run_case():
        return await lowlevel_worker.probe_capture_markers(
            frames=[SimpleNamespace(duration=1.0)],
            stt=FakeSTT("check tests"),
            queue=TaskQueue(tmp_path / "tasks.jsonl"),
            events=events,
            usage=UsageLog(tmp_path / "usage.jsonl"),
            tts_publisher=speaker,
            capture_session=capture_session,
            now=10.0,
        )

    action = asyncio.run(run_case())

    assert action.kind == lowlevel_worker.CaptureActionKind.IGNORE
    assert capture_session.is_capturing is True
    assert speaker.enqueued_tones == []
    assert [event.type for event in events.read_all()] == [
        "marker_probe.started",
        "marker_probe.result",
    ]


def test_marker_probe_cancels_active_capture_before_regular_vad_end(tmp_path) -> None:
    speaker = FakeSpeechQueue()
    backend = FakeAgentBackend(reply="done")
    capture_session = MarkerCaptureSession(CaptureConfig(mode=CaptureMode.MARKERS))
    capture_session.handle_text("start command", now=9.0)
    capture_session.mark_ready(now=9.5)
    capture_session.handle_text("check tests", now=10.0)
    events = EventLog(tmp_path / "events.jsonl")

    async def run_case():
        return await lowlevel_worker.probe_capture_markers(
            frames=[SimpleNamespace(duration=1.0)],
            stt=FakeSTT("cancel"),
            queue=TaskQueue(tmp_path / "tasks.jsonl"),
            events=events,
            usage=UsageLog(tmp_path / "usage.jsonl"),
            tts_publisher=speaker,
            agent_backend=backend,
            agent_runs=AgentRunStore(tmp_path / "agent_runs.jsonl"),
            capture_session=capture_session,
            now=11.0,
        )

    action = asyncio.run(run_case())

    assert action.kind == lowlevel_worker.CaptureActionKind.CANCELLED
    assert capture_session.is_capturing is False
    assert backend.prompts == []
    assert speaker.enqueued_tones == ["capture_cancel"]
    assert [event.type for event in events.read_all()] == [
        "marker_probe.started",
        "marker_probe.result",
        "capture.cancelled",
    ]


def test_marker_probe_cancels_active_capture_with_cancel_word_and_trailing_text(tmp_path) -> None:
    speaker = FakeSpeechQueue()
    capture_session = MarkerCaptureSession(CaptureConfig(mode=CaptureMode.MARKERS))
    capture_session.handle_text("start command", now=9.0)
    capture_session.mark_ready(now=9.5)
    capture_session.handle_text("check tests", now=10.0)
    events = EventLog(tmp_path / "events.jsonl")

    async def run_case():
        return await lowlevel_worker.probe_capture_markers(
            frames=[SimpleNamespace(duration=1.0)],
            stt=FakeSTT("cancel now"),
            queue=TaskQueue(tmp_path / "tasks.jsonl"),
            events=events,
            usage=UsageLog(tmp_path / "usage.jsonl"),
            tts_publisher=speaker,
            capture_session=capture_session,
            now=11.0,
        )

    action = asyncio.run(run_case())

    assert action.kind == lowlevel_worker.CaptureActionKind.CANCELLED
    assert capture_session.is_capturing is False
    assert speaker.enqueued_tones == ["capture_cancel"]
    assert [event.type for event in events.read_all()] == [
        "marker_probe.started",
        "marker_probe.result",
        "capture.cancelled",
    ]


def test_marker_probe_ignores_active_submit_marker(tmp_path) -> None:
    speaker = FakeSpeechQueue()
    backend = FakeAgentBackend(reply="done")
    capture_session = MarkerCaptureSession(CaptureConfig(mode=CaptureMode.MARKERS))
    capture_session.handle_text("start command", now=9.0)
    capture_session.mark_ready(now=9.5)
    capture_session.handle_text("check", now=10.0)
    agent_tasks: set[asyncio.Task] = set()
    events = EventLog(tmp_path / "events.jsonl")
    runs = AgentRunStore(tmp_path / "agent_runs.jsonl")

    async def run_case():
        action = await lowlevel_worker.probe_capture_markers(
            frames=[SimpleNamespace(duration=1.0)],
            stt=FakeSTT("tests send command"),
            queue=TaskQueue(tmp_path / "tasks.jsonl"),
            events=events,
            usage=UsageLog(tmp_path / "usage.jsonl"),
            tts_publisher=speaker,
            agent_backend=backend,
            agent_runs=runs,
            agent_tasks=agent_tasks,
            capture_session=capture_session,
            now=11.0,
        )
        await asyncio.gather(*agent_tasks)
        return action

    action = asyncio.run(run_case())

    assert action.kind == lowlevel_worker.CaptureActionKind.IGNORE
    assert capture_session.is_capturing is True
    assert backend.prompts == []
    assert speaker.enqueued_tones == []
    assert speaker.enqueued_texts == []
    assert [event.type for event in events.read_all()] == [
        "marker_probe.started",
        "marker_probe.result",
    ]


def test_capture_timeout_cancels_buffer(tmp_path) -> None:
    speaker = FakeSpeechQueue()
    capture_session = MarkerCaptureSession(CaptureConfig(mode=CaptureMode.MARKERS, silence_timeout_seconds=5.0))
    events = EventLog(tmp_path / "events.jsonl")

    capture_session.handle_text("start command", now=10.0)
    capture_session.mark_ready(now=10.5)
    capture_session.handle_text("check tests", now=11.0)

    cancelled = lowlevel_worker.handle_capture_timeout(
        capture_session=capture_session,
        events=events,
        tts_publisher=speaker,
        now=16.0,
    )

    assert cancelled is True
    assert speaker.enqueued_texts == []
    assert speaker.enqueued_tones == ["capture_cancel"]
    assert events.read_all()[0].type == "capture.cancelled"
    assert events.read_all()[0].payload["reason"] == "silence_timeout"


def test_control_reset_clears_active_capture_session(tmp_path) -> None:
    events = EventLog(tmp_path / "events.jsonl")
    capture_session = MarkerCaptureSession(CaptureConfig(mode=CaptureMode.MARKERS))
    capture_session.handle_text("start command", now=0.0)
    capture_session.mark_ready(now=0.5)
    capture_session.handle_text("check tests", now=1.0)

    handled = lowlevel_worker.handle_control_event(
        capture_session=capture_session,
        events=events,
        event_type="control.reset_requested",
        payload={"source": "ios"},
    )

    assert handled is True
    assert capture_session.is_capturing is False
    reset_events = events.read_all()
    assert reset_events[0].type == "capture.reset"
    assert reset_events[0].payload == {"reason": "external_reset", "source": "ios"}


def test_consume_claude_replies_speaks_sse_replies(tmp_path) -> None:
    speaker = FakeSpeaker()
    events = EventLog(tmp_path / "events.jsonl")

    asyncio.run(
        lowlevel_worker.consume_claude_replies(
            reply_stream=FakeClaudeReplyStream([ClaudeReply(chat_id="voice", text="Done", status="done")]),
            tts_publisher=speaker,
            events=events,
            max_replies=1,
        )
    )

    assert speaker.spoken_texts == ["Done"]
    assert [event.type for event in events.read_all()] == ["claude_channel.reply"]


def test_recognize_and_route_speech_records_empty_transcript_without_routing(tmp_path) -> None:
    stt = FakeSTT("")
    queue = TaskQueue(tmp_path / "tasks.jsonl")
    events = EventLog(tmp_path / "events.jsonl")
    usage = UsageLog(tmp_path / "usage.jsonl")

    result = asyncio.run(
        lowlevel_worker.recognize_and_route_speech(
            frames=[SimpleNamespace(duration=0.5)],
            stt=stt,
            queue=queue,
            events=events,
            usage=usage,
        )
    )

    assert result.transcript == ""
    assert result.reply == ""
    assert queue.list_tasks() == []
    assert [event.type for event in events.read_all()] == ["vad.speech", "stt.empty"]


def test_recognize_and_route_speech_records_stt_error_without_crashing(tmp_path) -> None:
    stt = FailingSTT()
    queue = TaskQueue(tmp_path / "tasks.jsonl")
    events = EventLog(tmp_path / "events.jsonl")
    usage = UsageLog(tmp_path / "usage.jsonl")

    result = asyncio.run(
        lowlevel_worker.recognize_and_route_speech(
            frames=[SimpleNamespace(duration=0.5)],
            stt=stt,
            queue=queue,
            events=events,
            usage=usage,
        )
    )

    assert result.transcript == ""
    assert result.reply == ""
    assert queue.list_tasks() == []
    assert [event.type for event in events.read_all()] == ["vad.speech", "stt.error"]


def test_build_deepgram_stt_passes_owned_http_session() -> None:
    stt_api_key = "test-stt-value"
    voice_config = SimpleNamespace(deepgram_api_key=stt_api_key, deepgram_language="en")
    session = object()

    stt = lowlevel_worker.build_deepgram_stt(
        deepgram_module=FakeDeepgramModule,
        voice_config=voice_config,
        http_session=session,
    )

    assert stt.kwargs["api_key"] == stt_api_key
    assert stt.kwargs["model"] == "nova-3"
    assert stt.kwargs["language"] == "en"
    assert stt.kwargs["http_session"] is session


def test_build_agent_backend_creates_codex_app_server_backend(tmp_path) -> None:
    backend = lowlevel_worker.build_agent_backend(
        lowlevel_worker.LowLevelWorkerConfig(
            room="line-dev",
            identity="line-worker",
            agent_backend="codex-app-server",
            agent_model="gpt-5.5",
            agent_cwd=tmp_path,
            agent_timeout_seconds=120.0,
            codex_endpoint="ws://127.0.0.1:4500",
            codex_thread_id="thread-existing",
        )
    )

    assert backend is not None
    assert backend.label == "codex"
    assert backend.model == "gpt-5.5"
    assert backend.config.cwd == tmp_path
    assert backend.config.timeout_seconds == 120.0
    assert backend.config.endpoint == "ws://127.0.0.1:4500"
    assert backend.config.thread_id == "thread-existing"


def test_close_agent_backend_calls_optional_aclose() -> None:
    backend = ClosableAgentBackend()

    asyncio.run(lowlevel_worker.close_agent_backend(backend))

    assert backend.closed is True


def test_extract_final_transcript_reads_first_alternative() -> None:
    assert lowlevel_worker.extract_final_transcript(FakeSpeechEvent("text")) == "text"


def test_audio_frame_stats_reads_int16_pcm() -> None:
    frame = SimpleNamespace(data=b"\x00\x00\x00@\x00\xc0")

    stats = lowlevel_worker.audio_frame_stats(frame)

    assert stats is not None
    assert stats.samples == 3
    assert round(stats.peak, 3) == 0.5
    assert round(stats.rms, 3) == 0.408


def test_audio_frame_stats_ignores_empty_pcm() -> None:
    assert lowlevel_worker.audio_frame_stats(SimpleNamespace(data=b"")) is None


def test_is_audio_activity_ignores_zeroed_pcm() -> None:
    stats = lowlevel_worker.audio_frame_stats(SimpleNamespace(data=b"\x00\x00\x00\x00"))

    assert stats is not None
    assert lowlevel_worker.is_audio_activity(stats) is False


def test_is_audio_activity_ignores_residual_low_noise() -> None:
    stats = lowlevel_worker.audio_frame_stats(SimpleNamespace(data=(100).to_bytes(2, "little", signed=True) * 8))

    assert stats is not None
    assert round(stats.rms, 4) == 0.0031
    assert lowlevel_worker.is_audio_activity(stats) is False


def test_is_audio_activity_accepts_speech_like_pcm() -> None:
    stats = lowlevel_worker.audio_frame_stats(SimpleNamespace(data=b"\x00@\x00\xc0"))

    assert stats is not None
    assert lowlevel_worker.is_audio_activity(stats) is True


def test_is_audio_track_accepts_livekit_audio_kind_value() -> None:
    assert lowlevel_worker.is_audio_track(SimpleNamespace(kind=1)) is True
    assert lowlevel_worker.is_audio_track(SimpleNamespace(kind=2)) is False


def test_should_listen_to_participant_ignores_self_and_livekit_agents() -> None:
    assert lowlevel_worker.should_listen_to_participant("line-worker", "line-worker") is False
    assert lowlevel_worker.should_listen_to_participant("agent-AJ_123", "line-worker") is False
    assert lowlevel_worker.should_listen_to_participant("mac-test", "line-worker") is True


def test_should_spawn_audio_task_allows_one_active_track_per_participant() -> None:
    active = set()

    assert lowlevel_worker.should_spawn_audio_task(
        participant_identity="mac-test",
        worker_identity="line-worker",
        active_audio_participants=active,
    ) is True
    active.add("mac-test")
    assert lowlevel_worker.should_spawn_audio_task(
        participant_identity="mac-test",
        worker_identity="line-worker",
        active_audio_participants=active,
    ) is False
    assert lowlevel_worker.should_spawn_audio_task(
        participant_identity="other",
        worker_identity="line-worker",
        active_audio_participants=active,
    ) is True


class FakeSTT:
    def __init__(self, text: str) -> None:
        self._text = text
        self.frames = None

    async def recognize(self, frames):
        self.frames = frames
        return FakeSpeechEvent(self._text)


class FailingSTT:
    async def recognize(self, frames):
        del frames
        raise RuntimeError("deepgram unavailable")


class FakeSpeaker:
    def __init__(self) -> None:
        self.spoken_texts: list[str] = []

    async def say(self, text: str) -> None:
        self.spoken_texts.append(text)


class FakeSpeechQueue:
    def __init__(self) -> None:
        self.enqueued_texts: list[str] = []
        self.enqueued_tones: list[str] = []

    def enqueue(self, text: str) -> None:
        self.enqueued_texts.append(text)

    def enqueue_tone(self, cue: str) -> None:
        self.enqueued_tones.append(cue)


class FakeClaudeChannelClient:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send_voice_message(self, text: str, chat_id: str = "voice"):
        self.sent.append((text, chat_id))
        return {"ok": True, "chat_id": chat_id}


class FakeClaudeReplyStream:
    def __init__(self, replies: list[ClaudeReply]) -> None:
        self._replies = replies

    def iter_replies(self):
        yield from self._replies


class FakeAgentBackend:
    label = "haiku"

    def __init__(
        self,
        reply: str,
        *,
        voice_replies: tuple[VoiceReply, ...] = (),
        full_reply: str | None = None,
    ) -> None:
        self.reply = reply
        self.voice_replies = voice_replies
        self.full_reply = full_reply
        self.prompts: list[str] = []

    async def run(self, prompt: str) -> AgentJobResult:
        self.prompts.append(prompt)
        return AgentJobResult(
            prompt=prompt,
            reply=self.reply,
            model="haiku",
            stdout=self.reply,
            stderr="",
            full_reply=self.full_reply,
            spoken_reply=self.reply,
            voice_replies=self.voice_replies,
        )


class ClosableAgentBackend:
    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class FakeSpeechEvent:
    def __init__(self, text: str) -> None:
        self.alternatives = [SimpleNamespace(text=text)] if text else []


class FakeDeepgramModule:
    class STT:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs
