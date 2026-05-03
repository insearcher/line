from __future__ import annotations

import asyncio
from array import array
from dataclasses import dataclass
import inspect
import math
from pathlib import Path
import sys
from typing import Any

from line.agent_backends import (
    AgentBackendError,
    AgentJobResult,
    ClaudeCliBackend,
    ClaudeCliConfig,
    CodexAppServerBackend,
    CodexAppServerConfig,
    VoiceReply,
)
from line.agent_runs import AgentRunRecord, AgentRunStore
from line.capture import CaptureAction, CaptureActionKind, CaptureConfig, CaptureMode, MarkerCaptureSession
from line.cc_channel import CcChannelClient, CcReply, CcReplyStream
from line.events import EventLog
from line.routing_service import RouteResult, route_transcript
from line.settings import VoiceConfig, load_env_file
from line.speech_queue import SpeechQueue
from line.task_queue import TaskQueue
from line.time_utils import utc_now_iso
from line.tokens import generate_join_token
from line.tts_publisher import TTSPublisher, build_tts_provider
from line.usage import UsageLog


AUDIO_ACTIVITY_RMS_THRESHOLD = 0.01


@dataclass(frozen=True)
class LowLevelWorkerConfig:
    room: str
    identity: str
    env_path: Path = Path(".env")
    events_path: Path = Path("data/events.jsonl")
    queue_path: Path = Path("data/line_tasks.jsonl")
    usage_path: Path = Path("data/usage.jsonl")
    control_path: Path = Path("data/control.jsonl")
    cc_channel_url: str | None = None
    cc_channel_token: str | None = None
    agent_backend: str = "router"
    agent_model: str = "haiku"
    agent_cwd: Path | None = None
    codex_endpoint: str | None = None
    codex_thread_id: str | None = None
    agent_permission_mode: str | None = None
    agent_timeout_seconds: float = 900.0
    agent_max_budget_usd: float | None = None
    agent_runs_path: Path = Path("data/agent_runs.jsonl")
    capture_config: CaptureConfig = CaptureConfig()


@dataclass(frozen=True)
class SpeechRouteResult:
    created_at: str
    transcript: str
    reply: str
    route: RouteResult | None


@dataclass(frozen=True)
class AudioFrameStats:
    rms: float
    peak: float
    samples: int


@dataclass(frozen=True)
class MarkerProbeConfig:
    window_seconds: float = 3.0
    min_audio_seconds: float = 1.0
    interval_seconds: float = 1.5


class RollingMarkerProbe:
    def __init__(self, config: MarkerProbeConfig = MarkerProbeConfig()) -> None:
        self.config = config
        self._frames: list[Any] = []
        self._duration = 0.0
        self._next_probe_at = 0.0

    def add_frames(self, frames: list[Any]) -> RollingMarkerProbe:
        for frame in frames:
            duration = _frame_duration(frame)
            if duration <= 0:
                continue
            self._frames.append(frame)
            self._duration += duration
        self._trim_to_window()
        return self

    def snapshot_if_due(self, *, now: float) -> list[Any] | None:
        if self._duration < self.config.min_audio_seconds:
            return None
        if now < self._next_probe_at:
            return None
        self._next_probe_at = now + self.config.interval_seconds
        return list(self._frames)

    def clear(self) -> None:
        self._frames = []
        self._duration = 0.0

    def discard_prefix(self, frames: list[Any]) -> None:
        remaining = len(frames)
        while remaining > 0 and self._frames:
            self._duration -= _frame_duration(self._frames.pop(0))
            remaining -= 1
        if self._duration < 0:
            self._duration = 0.0

    def _trim_to_window(self) -> None:
        while self._frames and self._duration > self.config.window_seconds:
            self._duration -= _frame_duration(self._frames.pop(0))


def run_lowlevel_worker(config: LowLevelWorkerConfig) -> None:
    asyncio.run(run_lowlevel_worker_async(config))


async def run_lowlevel_worker_async(config: LowLevelWorkerConfig) -> None:
    try:
        from livekit import rtc
        from livekit.plugins import deepgram, elevenlabs, silero
    except ImportError as error:
        raise RuntimeError("Voice dependencies are not installed. Run: uv sync --extra voice") from error

    load_env_file(config.env_path)
    voice_config = VoiceConfig.from_env()
    events = EventLog(config.events_path)
    usage = UsageLog(config.usage_path)
    queue = TaskQueue(config.queue_path)
    room = rtc.Room()
    import aiohttp

    http_session = aiohttp.ClientSession()
    stt = build_deepgram_stt(
        deepgram_module=deepgram,
        voice_config=voice_config,
        http_session=http_session,
    )
    tts = build_tts_provider(
        config=voice_config,
        deepgram_module=deepgram,
        elevenlabs_module=elevenlabs,
        http_session=http_session,
    )
    tts_publisher = TTSPublisher(
        room=room,
        rtc_module=rtc,
        tts=tts,
        events=events,
        usage=usage,
    )
    speech_queue = SpeechQueue(tts_publisher)
    cc_channel_client = (
        CcChannelClient(base_url=config.cc_channel_url, token=config.cc_channel_token)
        if config.cc_channel_url
        else None
    )
    cc_reply_stream = (
        CcReplyStream(base_url=config.cc_channel_url, token=config.cc_channel_token)
        if config.cc_channel_url
        else None
    )
    agent_backend = build_agent_backend(config)
    agent_runs = AgentRunStore(config.agent_runs_path) if agent_backend is not None else None
    capture_session = (
        MarkerCaptureSession(config.capture_config)
        if config.capture_config.mode == CaptureMode.MARKERS
        else None
    )
    vad = silero.VAD.load(sample_rate=16000)
    token = generate_join_token(config=voice_config, room=config.room, identity=config.identity)
    active_tasks: set[asyncio.Task] = set()
    background_tasks: set[asyncio.Task] = set()
    active_audio_participants: set[str] = set()
    disconnected = asyncio.Event()

    def spawn_audio_task(track: Any, participant: Any) -> None:
        participant_identity = getattr(participant, "identity", "")
        if not should_spawn_audio_task(
            participant_identity=participant_identity,
            worker_identity=config.identity,
            active_audio_participants=active_audio_participants,
        ):
            return
        active_audio_participants.add(participant_identity)
        task = asyncio.create_task(
            handle_audio_track(
                track=track,
                participant_identity=participant_identity or "unknown",
                vad=vad,
                stt=stt,
                queue=queue,
                events=events,
                usage=usage,
                tts_publisher=speech_queue,
                cc_channel_client=cc_channel_client,
                agent_backend=agent_backend,
                agent_runs=agent_runs,
                capture_session=capture_session,
                agent_tasks=background_tasks,
            )
        )
        active_tasks.add(task)

        def on_audio_task_done(done_task: asyncio.Task) -> None:
            active_tasks.discard(done_task)
            active_audio_participants.discard(participant_identity)

        task.add_done_callback(on_audio_task_done)

    @room.on("track_subscribed")
    def on_track_subscribed(track: Any, publication: Any, participant: Any) -> None:
        del publication
        if is_audio_track(track):
            events.append(
                "livekit.track_subscribed",
                {
                    "participant": getattr(participant, "identity", "unknown"),
                    "track": getattr(track, "sid", ""),
                },
            )
            spawn_audio_task(track, participant)

    @room.on("disconnected")
    def on_disconnected(reason: Any) -> None:
        events.append("livekit.disconnected", {"reason": str(reason)})
        disconnected.set()

    events.append(
        "livekit.worker_connecting",
        {"room": config.room, "identity": config.identity},
    )
    await room.connect(voice_config.livekit_url, token)
    events.append("livekit.worker_connected", {"room": config.room, "identity": config.identity})
    await tts_publisher.start()
    await speech_queue.start()
    if cc_reply_stream is not None:
        task = asyncio.create_task(
            consume_cc_replies(
                reply_stream=cc_reply_stream,
                tts_publisher=speech_queue,
                events=events,
            )
        )
        background_tasks.add(task)
        task.add_done_callback(background_tasks.discard)
    if capture_session is not None:
        task = asyncio.create_task(
            watch_capture_timeout(
                capture_session=capture_session,
                events=events,
                tts_publisher=speech_queue,
            )
        )
        background_tasks.add(task)
        task.add_done_callback(background_tasks.discard)
        task = asyncio.create_task(
            watch_control_events(
                control_path=config.control_path,
                capture_session=capture_session,
                events=events,
            )
        )
        background_tasks.add(task)
        task.add_done_callback(background_tasks.discard)

    try:
        await disconnected.wait()
    finally:
        for task in background_tasks:
            task.cancel()
        for task in active_tasks:
            task.cancel()
        if background_tasks:
            await asyncio.gather(*background_tasks, return_exceptions=True)
        if active_tasks:
            await asyncio.gather(*active_tasks, return_exceptions=True)
        await close_agent_backend(agent_backend)
        await speech_queue.aclose()
        await tts_publisher.aclose()
        await room.disconnect()
        await http_session.close()


async def handle_audio_track(
    *,
    track: Any,
    participant_identity: str,
    vad: Any,
    stt: Any,
    queue: TaskQueue,
    events: EventLog,
    usage: UsageLog,
    tts_publisher: Any | None = None,
    cc_channel_client: CcChannelClient | None = None,
    agent_backend: Any | None = None,
    agent_runs: AgentRunStore | None = None,
    capture_session: MarkerCaptureSession | None = None,
    agent_tasks: set[asyncio.Task] | None = None,
) -> None:
    from livekit import rtc
    from livekit.agents.vad import VADEventType

    events.append("audio.track_started", {"participant": participant_identity})
    audio_stream = rtc.AudioStream.from_track(
        track=track,
        sample_rate=16000,
        num_channels=1,
        frame_size_ms=100,
    )
    vad_stream = vad.stream()
    marker_probe = RollingMarkerProbe() if capture_session is not None else None
    marker_probe_tasks: set[asyncio.Task] = set()
    skip_next_vad_end = False
    skip_next_vad_end_reason = "marker_probe"

    async def consume_audio() -> None:
        loop = asyncio.get_running_loop()
        last_level_log_at = loop.time()
        level_frames = 0
        max_rms = 0.0
        max_peak = 0.0
        last_rms = 0.0
        last_peak = 0.0
        async for audio_event in audio_stream:
            frame = audio_event.frame
            if stats := audio_frame_stats(frame):
                if is_audio_activity(stats):
                    usage.record_seconds("audio.received", frame.duration)
                level_frames += 1
                max_rms = max(max_rms, stats.rms)
                max_peak = max(max_peak, stats.peak)
                last_rms = stats.rms
                last_peak = stats.peak
                now = loop.time()
                if now - last_level_log_at >= 1.0:
                    if max_rms >= AUDIO_ACTIVITY_RMS_THRESHOLD:
                        events.append(
                            "audio.level",
                            {
                                "participant": participant_identity,
                                "frames": level_frames,
                                "last_peak": round(last_peak, 5),
                                "last_rms": round(last_rms, 5),
                                "max_peak": round(max_peak, 5),
                                "max_rms": round(max_rms, 5),
                            },
                        )
                    last_level_log_at = now
                    level_frames = 0
                    max_rms = 0.0
                    max_peak = 0.0
            vad_stream.push_frame(frame)
        vad_stream.end_input()

    async def run_marker_probe(frames: list[Any], now: float) -> None:
        nonlocal skip_next_vad_end, skip_next_vad_end_reason
        try:
            action = await probe_capture_markers(
                frames=frames,
                stt=stt,
                queue=queue,
                capture_session=capture_session,
                events=events,
                usage=usage,
                tts_publisher=tts_publisher,
                cc_channel_client=cc_channel_client,
                agent_backend=agent_backend,
                agent_runs=agent_runs,
                agent_tasks=agent_tasks,
                now=now,
            )
        except Exception as error:  # noqa: BLE001 - defensive boundary around background probe
            events.append("marker_probe.error", {"error": format_error(error)})
            return
        if action.kind != CaptureActionKind.IGNORE:
            skip_next_vad_end = True
            skip_next_vad_end_reason = f"marker_probe_{action.kind.value}"
            if marker_probe is not None and action.kind in {
                CaptureActionKind.STARTED,
                CaptureActionKind.CANCELLED,
                CaptureActionKind.SUBMITTED,
            }:
                marker_probe.clear()
            elif marker_probe is not None:
                marker_probe.discard_prefix(frames)

    def maybe_spawn_marker_probe(vad_event: Any) -> None:
        if marker_probe is None or capture_session is None:
            return
        if capture_session.is_capturing and capture_session.deadline is None:
            marker_probe.clear()
            return
        if not getattr(vad_event, "speaking", False):
            return
        frames = list(getattr(vad_event, "frames", []) or [])
        now = asyncio.get_running_loop().time()
        probe_frames = marker_probe.add_frames(frames).snapshot_if_due(now=now)
        if probe_frames is None or marker_probe_tasks:
            return
        task = asyncio.create_task(run_marker_probe(probe_frames, now))
        marker_probe_tasks.add(task)
        task.add_done_callback(marker_probe_tasks.discard)

    async def consume_vad() -> None:
        nonlocal skip_next_vad_end, skip_next_vad_end_reason
        async for vad_event in vad_stream:
            if vad_event.type == VADEventType.START_OF_SPEECH and marker_probe is not None:
                marker_probe.clear()
            if vad_event.type == VADEventType.INFERENCE_DONE:
                maybe_spawn_marker_probe(vad_event)
                continue
            if vad_event.type != VADEventType.END_OF_SPEECH:
                continue
            if skip_next_vad_end:
                skip_next_vad_end = False
                events.append("marker_probe.vad_end_skipped", {"reason": skip_next_vad_end_reason})
                continue
            await recognize_and_route_speech(
                frames=vad_event.frames,
                stt=stt,
                queue=queue,
                events=events,
                usage=usage,
                tts_publisher=tts_publisher,
                cc_channel_client=cc_channel_client,
                agent_backend=agent_backend,
                agent_runs=agent_runs,
                capture_session=capture_session,
                agent_tasks=agent_tasks,
            )

    try:
        await asyncio.gather(consume_audio(), consume_vad())
    finally:
        for task in marker_probe_tasks:
            task.cancel()
        if marker_probe_tasks:
            await asyncio.gather(*marker_probe_tasks, return_exceptions=True)
        await audio_stream.aclose()
        await vad_stream.aclose()
        events.append("audio.track_stopped", {"participant": participant_identity})


async def recognize_and_route_speech(
    *,
    frames: list[Any],
    stt: Any,
    queue: TaskQueue,
    events: EventLog,
    usage: UsageLog,
    tts_publisher: Any | None = None,
    cc_channel_client: CcChannelClient | None = None,
    agent_backend: Any | None = None,
    agent_runs: AgentRunStore | None = None,
    capture_session: MarkerCaptureSession | None = None,
    agent_tasks: set[asyncio.Task] | None = None,
) -> SpeechRouteResult:
    created_at = utc_now_iso()
    speech_seconds = _frames_duration(frames)
    usage.record_seconds("vad.speech", speech_seconds, created_at=created_at)
    events.append(
        "vad.speech",
        {"seconds": speech_seconds, "frames": len(frames)},
        created_at=created_at,
    )

    try:
        stt_event = await stt.recognize(frames)
    except Exception as error:  # noqa: BLE001 - boundary around external STT provider
        events.append(
            "stt.error",
            {"error": format_error(error), "seconds": speech_seconds},
            created_at=created_at,
        )
        return SpeechRouteResult(created_at=created_at, transcript="", reply="", route=None)

    usage.record_seconds("stt.audio", speech_seconds, created_at=created_at)
    transcript = extract_final_transcript(stt_event)
    if not transcript:
        events.append("stt.empty", {"seconds": speech_seconds}, created_at=created_at)
        return SpeechRouteResult(created_at=created_at, transcript="", reply="", route=None)

    events.append(
        "stt.result",
        {"text": transcript, "seconds": speech_seconds},
        created_at=created_at,
    )
    suppress_agent_ack = False
    if capture_session is not None:
        action_now = asyncio.get_running_loop().time()
        action = capture_session.handle_text(transcript, now=action_now)
        capture_prompt = await handle_capture_action(
            action=action,
            events=events,
            tts_publisher=tts_publisher,
            capture_session=capture_session,
            created_at=created_at,
            now=action_now,
        )
        if capture_prompt is None:
            return SpeechRouteResult(created_at=created_at, transcript=transcript, reply=action.reply or "", route=None)
        transcript = capture_prompt
        suppress_agent_ack = True

    return await dispatch_recognized_text(
        created_at=created_at,
        transcript=transcript,
        queue=queue,
        events=events,
        tts_publisher=tts_publisher,
        cc_channel_client=cc_channel_client,
        agent_backend=agent_backend,
        agent_runs=agent_runs,
        agent_tasks=agent_tasks,
        suppress_agent_ack=suppress_agent_ack,
    )


async def dispatch_recognized_text(
    *,
    created_at: str,
    transcript: str,
    queue: TaskQueue,
    events: EventLog,
    tts_publisher: Any | None = None,
    cc_channel_client: CcChannelClient | None = None,
    agent_backend: Any | None = None,
    agent_runs: AgentRunStore | None = None,
    agent_tasks: set[asyncio.Task] | None = None,
    suppress_agent_ack: bool = False,
) -> SpeechRouteResult:
    if cc_channel_client is not None:
        try:
            await asyncio.to_thread(cc_channel_client.send_voice_message, transcript, "voice")
        except Exception as error:  # noqa: BLE001 - boundary around local HTTP bridge
            events.append(
                "cc_channel.error",
                {"error": format_error(error), "text": transcript},
                created_at=created_at,
            )
        else:
            events.append(
                "cc_channel.sent",
                {"text": transcript, "chat_id": "voice"},
                created_at=created_at,
            )
        return SpeechRouteResult(created_at=created_at, transcript=transcript, reply="", route=None)

    if agent_backend is not None:
        label = str(getattr(agent_backend, "label", "agent"))
        model = str(getattr(agent_backend, "model", label))
        run = (
            agent_runs.create_queued(backend=label, model=model, prompt=transcript, created_at=created_at)
            if agent_runs is not None
            else None
        )
        reply = build_agent_ack(label=label, prompt=transcript)
        events.append(
            "agent_backend.dispatched",
            {"backend": label, "model": model, "run_id": run.id if run else None, "text": transcript},
            created_at=created_at,
        )
        if not suppress_agent_ack:
            await deliver_speech(tts_publisher, reply)
        task = asyncio.create_task(
            run_agent_backend_job(
                agent_backend=agent_backend,
                prompt=transcript,
                tts_publisher=tts_publisher,
                events=events,
                agent_runs=agent_runs,
                run=run,
            )
        )
        if agent_tasks is not None:
            agent_tasks.add(task)
            task.add_done_callback(agent_tasks.discard)
        return SpeechRouteResult(
            created_at=created_at,
            transcript=transcript,
            reply="" if suppress_agent_ack else reply,
            route=None,
        )

    route = route_transcript(text=transcript, queue=queue, events=events)
    if tts_publisher is not None and route.reply:
        await deliver_speech(tts_publisher, route.reply)
    return SpeechRouteResult(
        created_at=created_at,
        transcript=transcript,
        reply=route.reply,
        route=route,
    )


async def probe_for_capture_start(
    *,
    frames: list[Any],
    stt: Any,
    capture_session: MarkerCaptureSession | None,
    events: EventLog,
    usage: UsageLog,
    tts_publisher: Any | None,
    now: float,
) -> bool:
    action = await probe_capture_markers(
        frames=frames,
        stt=stt,
        queue=None,
        capture_session=capture_session,
        events=events,
        usage=usage,
        tts_publisher=tts_publisher,
        now=now,
    )
    return action.kind == CaptureActionKind.STARTED


async def probe_capture_markers(
    *,
    frames: list[Any],
    stt: Any,
    queue: TaskQueue | None,
    events: EventLog,
    usage: UsageLog,
    tts_publisher: Any | None,
    capture_session: MarkerCaptureSession | None,
    now: float,
    cc_channel_client: CcChannelClient | None = None,
    agent_backend: Any | None = None,
    agent_runs: AgentRunStore | None = None,
    agent_tasks: set[asyncio.Task] | None = None,
) -> CaptureAction:
    if capture_session is None:
        return CaptureAction(kind=CaptureActionKind.IGNORE, text="")
    if capture_session.is_capturing and capture_session.deadline is None:
        return CaptureAction(kind=CaptureActionKind.IGNORE, text="")

    created_at = utc_now_iso()
    speech_seconds = _frames_duration(frames)
    events.append("marker_probe.started", {"seconds": speech_seconds}, created_at=created_at)

    try:
        stt_event = await stt.recognize(frames)
    except Exception as error:  # noqa: BLE001 - boundary around external STT provider
        events.append(
            "marker_probe.error",
            {"error": format_error(error), "seconds": speech_seconds},
            created_at=created_at,
        )
        return CaptureAction(kind=CaptureActionKind.IGNORE, text="")

    usage.record_seconds("stt.marker_probe", speech_seconds, created_at=created_at)
    transcript = extract_final_transcript(stt_event)
    events.append(
        "marker_probe.result",
        {"text": transcript, "seconds": speech_seconds},
        created_at=created_at,
    )
    if not transcript:
        return CaptureAction(kind=CaptureActionKind.IGNORE, text="")

    if capture_session.deadline is not None:
        action = capture_session.handle_cancel_text(transcript)
    else:
        action = capture_session.handle_text(transcript, now=now)
    capture_prompt = await handle_capture_action(
        action=action,
        events=events,
        tts_publisher=tts_publisher,
        capture_session=capture_session,
        created_at=created_at,
        now=now,
    )
    if capture_prompt is not None:
        if queue is None:
            return action
        await dispatch_recognized_text(
            created_at=created_at,
            transcript=capture_prompt,
            queue=queue,
            events=events,
            tts_publisher=tts_publisher,
            cc_channel_client=cc_channel_client,
            agent_backend=agent_backend,
            agent_runs=agent_runs,
            agent_tasks=agent_tasks,
            suppress_agent_ack=True,
        )
    return action


async def handle_capture_action(
    *,
    action: CaptureAction,
    events: EventLog,
    tts_publisher: Any | None,
    capture_session: MarkerCaptureSession | None = None,
    created_at: str | None = None,
    now: float | None = None,
) -> str | None:
    if action.kind == CaptureActionKind.IGNORE:
        return None
    if action.kind == CaptureActionKind.STARTED:
        events.append(
            "capture.started",
            {"text": action.text, "buffer": action.buffer_text},
            created_at=created_at,
        )
        await deliver_tone(tts_publisher, "capture_start")
        await wait_for_speech_output(tts_publisher)
        if capture_session is not None:
            capture_session.mark_ready(now=now if now is not None else asyncio.get_running_loop().time())
        if action.reply:
            await deliver_speech(tts_publisher, action.reply)
        return None
    if action.kind == CaptureActionKind.BUFFERED:
        events.append(
            "capture.buffered",
            {"text": action.text, "buffer": action.buffer_text},
            created_at=created_at,
        )
        return None
    if action.kind == CaptureActionKind.CANCELLED:
        events.append(
            "capture.cancelled",
            {"text": action.text, "reason": action.reason},
            created_at=created_at,
        )
        await deliver_tone(tts_publisher, "capture_cancel")
        return None
    if action.kind == CaptureActionKind.SUBMITTED:
        events.append(
            "capture.submitted",
            {"text": action.text, "prompt": action.prompt},
            created_at=created_at,
        )
        await deliver_tone(tts_publisher, "capture_submit")
        if action.reply:
            await deliver_speech(tts_publisher, action.reply)
        return action.prompt
    return None


async def watch_capture_timeout(
    *,
    capture_session: MarkerCaptureSession,
    events: EventLog,
    tts_publisher: Any | None,
    interval_seconds: float = 0.25,
) -> None:
    while True:
        handle_capture_timeout(
            capture_session=capture_session,
            events=events,
            tts_publisher=tts_publisher,
            now=asyncio.get_running_loop().time(),
        )
        await asyncio.sleep(interval_seconds)


def handle_capture_timeout(
    *,
    capture_session: MarkerCaptureSession,
    events: EventLog,
    tts_publisher: Any | None,
    now: float,
) -> bool:
    action = capture_session.check_timeout(now=now)
    if action.kind != CaptureActionKind.CANCELLED:
        return False
    events.append(
        "capture.cancelled",
        {"text": action.text, "reason": action.reason},
    )
    enqueue_tone = getattr(tts_publisher, "enqueue_tone", None)
    if enqueue_tone is not None:
        enqueue_tone("capture_cancel")
    return True


async def watch_control_events(
    *,
    control_path: Path,
    capture_session: MarkerCaptureSession,
    events: EventLog,
    interval_seconds: float = 0.25,
) -> None:
    control_log = EventLog(control_path)
    existing = control_log.read_all()
    last_seen_id = existing[-1].id if existing else None
    while True:
        records = control_log.read_after(last_seen_id) if last_seen_id else control_log.read_all()
        for record in records:
            handle_control_event(
                capture_session=capture_session,
                events=events,
                event_type=record.type,
                payload=record.payload,
            )
            last_seen_id = record.id
        await asyncio.sleep(interval_seconds)


def handle_control_event(
    *,
    capture_session: MarkerCaptureSession,
    events: EventLog,
    event_type: str,
    payload: dict[str, Any],
) -> bool:
    if event_type != "control.reset_requested":
        return False
    capture_session.reset()
    events.append(
        "capture.reset",
        {
            "reason": "external_reset",
            "source": str(payload.get("source", "unknown")),
        },
    )
    return True


async def run_agent_backend_job(
    *,
    agent_backend: Any,
    prompt: str,
    tts_publisher: Any | None,
    events: EventLog,
    agent_runs: AgentRunStore | None = None,
    run: AgentRunRecord | None = None,
) -> None:
    label = str(getattr(agent_backend, "label", "agent"))
    terminal_voice_reply_spoken = False

    async def stream_voice_reply(reply: VoiceReply) -> None:
        nonlocal terminal_voice_reply_spoken
        spoken_text = shorten_for_voice(reply.text)
        if not spoken_text:
            return
        events.append(
            "agent_backend.voice_reply",
            {
                "backend": label,
                "run_id": run.id if run else None,
                "status": reply.status,
                "text": spoken_text,
            },
        )
        if tts_publisher is not None:
            await deliver_speech(tts_publisher, spoken_text)
            if reply.status in {"done", "reply", "error"}:
                terminal_voice_reply_spoken = True

    if agent_runs is not None and run is not None:
        run = agent_runs.mark_running(run.id)
    events.append(
        "agent_backend.running",
        {"backend": label, "run_id": run.id if run else None, "text": prompt},
    )
    try:
        result = await run_agent_backend_with_voice_replies(
            agent_backend,
            prompt,
            voice_reply_callback=stream_voice_reply,
        )
    except AgentBackendError as error:
        message = f"{label} returned an error: {format_error(error)}"
        events.append(
            "agent_backend.failed",
            {"backend": label, "run_id": run.id if run else None, "text": prompt, "error": format_error(error)},
        )
        if agent_runs is not None and run is not None:
            agent_runs.mark_failed(run.id, error=format_error(error))
        if tts_publisher is not None:
            await deliver_speech(tts_publisher, message)
        return
    except Exception as error:  # noqa: BLE001 - boundary around external agent process
        message = f"{label} crashed: {format_error(error)}"
        events.append(
            "agent_backend.failed",
            {"backend": label, "run_id": run.id if run else None, "text": prompt, "error": format_error(error)},
        )
        if agent_runs is not None and run is not None:
            agent_runs.mark_failed(run.id, error=format_error(error))
        if tts_publisher is not None:
            await deliver_speech(tts_publisher, message)
        return

    spoken_reply = shorten_for_voice(result.spoken_reply or result.reply)
    voice_replies = [
        {"text": reply.text, "status": reply.status}
        for reply in getattr(result, "voice_replies", ())
    ]
    if agent_runs is not None and run is not None:
        agent_runs.mark_done(run.id, reply=spoken_reply)
    events.append(
        "agent_backend.done",
        {
            "backend": label,
            "model": result.model,
            "run_id": run.id if run else None,
            "text": prompt,
            "reply": spoken_reply,
            "full_reply": result.full_reply,
            "voice_replies": voice_replies,
        },
    )
    if tts_publisher is not None and not terminal_voice_reply_spoken:
        await deliver_speech(tts_publisher, spoken_reply)


async def run_agent_backend_with_voice_replies(
    agent_backend: Any,
    prompt: str,
    *,
    voice_reply_callback: Any,
) -> AgentJobResult:
    run = getattr(agent_backend, "run")
    try:
        parameters = inspect.signature(run).parameters
    except (TypeError, ValueError):
        return await run(prompt)
    if "voice_reply_callback" in parameters or any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    ):
        return await run(prompt, voice_reply_callback=voice_reply_callback)
    return await run(prompt)


async def consume_cc_replies(
    *,
    reply_stream: CcReplyStream,
    tts_publisher: Any,
    events: EventLog,
    max_replies: int | None = None,
) -> None:
    iterator = reply_stream.iter_replies()
    received = 0
    while True:
        reply = await asyncio.to_thread(_next_reply_or_none, iterator)
        if reply is None:
            return
        events.append(
            "cc_channel.reply",
            {
                "chat_id": reply.chat_id,
                "status": reply.status,
                "text": reply.text,
            },
            created_at=reply.created_at,
        )
        await deliver_speech(tts_publisher, reply.text)
        received += 1
        if max_replies is not None and received >= max_replies:
            return


def _next_reply_or_none(iterator: Any) -> CcReply | None:
    try:
        return next(iterator)
    except StopIteration:
        return None


def build_agent_ack(*, label: str, prompt: str) -> str:
    return f"Accepted, sent {label}: {shorten_for_voice(prompt, limit=120)}."


async def deliver_speech(speaker: Any | None, text: str) -> None:
    if speaker is None:
        return
    enqueue = getattr(speaker, "enqueue", None)
    if enqueue is not None:
        enqueue(text)
        return
    say = getattr(speaker, "say", None)
    if say is not None:
        await say(text)
        return
    raise TypeError("speaker must provide enqueue(text) or say(text)")


async def deliver_tone(speaker: Any | None, cue: str) -> None:
    if speaker is None:
        return
    enqueue_tone = getattr(speaker, "enqueue_tone", None)
    if enqueue_tone is not None:
        enqueue_tone(cue)
        return
    play_tone = getattr(speaker, "play_tone", None)
    if play_tone is not None:
        await play_tone(cue)
        return
    raise TypeError("speaker must provide enqueue_tone(cue) or play_tone(cue)")


async def wait_for_speech_output(speaker: Any | None) -> None:
    if speaker is None:
        return
    join = getattr(speaker, "join", None)
    if join is None:
        return
    result = join()
    if inspect.isawaitable(result):
        await result


def shorten_for_voice(text: str, limit: int = 900) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return f"{compact[: limit - 1].rstrip()}…"


def extract_final_transcript(stt_event: Any) -> str:
    alternatives = getattr(stt_event, "alternatives", None) or []
    if not alternatives:
        return ""
    return str(getattr(alternatives[0], "text", "")).strip()


def audio_frame_stats(frame: Any) -> AudioFrameStats | None:
    raw = bytes(getattr(frame, "data", b""))
    usable_length = len(raw) - (len(raw) % 2)
    if usable_length <= 0:
        return None

    samples = array("h")
    samples.frombytes(raw[:usable_length])
    if sys.byteorder != "little":
        samples.byteswap()
    if not samples:
        return None

    peak_sample = max(abs(sample) for sample in samples)
    rms_sample = math.sqrt(sum(float(sample) * float(sample) for sample in samples) / len(samples))
    return AudioFrameStats(
        rms=rms_sample / 32768.0,
        peak=peak_sample / 32768.0,
        samples=len(samples),
    )


def is_audio_activity(stats: AudioFrameStats) -> bool:
    return stats.rms >= AUDIO_ACTIVITY_RMS_THRESHOLD


def build_deepgram_stt(*, deepgram_module: Any, voice_config: VoiceConfig, http_session: Any) -> Any:
    return deepgram_module.STT(
        api_key=voice_config.deepgram_api_key,
        model="nova-3",
        language=voice_config.deepgram_language,
        http_session=http_session,
    )


def build_agent_backend(config: LowLevelWorkerConfig) -> Any | None:
    if config.agent_backend == "router":
        return None
    if config.agent_backend == "claude-cli":
        return ClaudeCliBackend(
            ClaudeCliConfig(
                model=config.agent_model,
                cwd=config.agent_cwd,
                permission_mode=config.agent_permission_mode,
                timeout_seconds=config.agent_timeout_seconds,
                max_budget_usd=config.agent_max_budget_usd,
            )
        )
    if config.agent_backend == "codex-app-server":
        return CodexAppServerBackend(
            CodexAppServerConfig(
                endpoint=config.codex_endpoint,
                thread_id=config.codex_thread_id,
                cwd=config.agent_cwd,
                model=_codex_model_from_agent_model(config.agent_model),
                timeout_seconds=config.agent_timeout_seconds,
            )
        )
    raise ValueError(f"Unsupported agent backend: {config.agent_backend}")


def _codex_model_from_agent_model(agent_model: str) -> str | None:
    return None if agent_model == "haiku" else agent_model


async def close_agent_backend(agent_backend: Any | None) -> None:
    if agent_backend is None:
        return
    aclose = getattr(agent_backend, "aclose", None)
    if aclose is not None:
        await aclose()


def format_error(error: Exception) -> str:
    message = str(error).strip()
    if len(message) > 500:
        message = f"{message[:497]}..."
    return f"{error.__class__.__name__}: {message}" if message else error.__class__.__name__


def is_audio_track(track: Any) -> bool:
    kind = getattr(track, "kind", None)
    if kind == 1:
        return True
    return str(kind).lower().endswith("audio")


def should_listen_to_participant(participant_identity: str, worker_identity: str) -> bool:
    if participant_identity == worker_identity:
        return False
    if participant_identity.startswith("agent-"):
        return False
    return True


def should_spawn_audio_task(
    *,
    participant_identity: str,
    worker_identity: str,
    active_audio_participants: set[str],
) -> bool:
    if not should_listen_to_participant(participant_identity, worker_identity):
        return False
    return participant_identity not in active_audio_participants


def _frame_duration(frame: Any) -> float:
    return max(0.0, float(getattr(frame, "duration", 0.0)))


def _frames_duration(frames: list[Any]) -> float:
    return round(sum(_frame_duration(frame) for frame in frames), 3)
