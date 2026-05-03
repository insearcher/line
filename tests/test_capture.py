from __future__ import annotations

from line.capture import CaptureActionKind, CaptureConfig, MarkerCaptureSession


def test_marker_capture_ignores_speech_without_wake_start() -> None:
    session = MarkerCaptureSession(CaptureConfig(wake_word="codex", start_phrase="start command"))

    action = session.handle_text("I am talking to a person", now=0.0)

    assert action.kind == CaptureActionKind.IGNORE
    assert session.is_capturing is False


def test_marker_capture_starts_only_with_wake_and_start_phrase() -> None:
    session = MarkerCaptureSession(CaptureConfig(wake_word="codex", start_phrase="start command"))

    action = session.handle_text("Codex start command", now=10.0)

    assert action.kind == CaptureActionKind.STARTED
    assert action.reply is None
    assert session.is_capturing is True
    assert session.deadline is None


def test_marker_capture_waits_for_ready_before_buffering_text() -> None:
    session = MarkerCaptureSession(
        CaptureConfig(
            wake_word="",
            start_phrase="start command",
            submit_phrase="send command",
        )
    )

    started = session.handle_text("Start command. Hello, can you hear me? Send command.", now=10.0)
    ignored = session.handle_text("this text arrived before the cue", now=10.5)
    ready = session.mark_ready(now=11.0)
    submitted = session.handle_text("Check tests. Send command.", now=12.0)

    assert started.kind == CaptureActionKind.STARTED
    assert started.buffer_text is None
    assert ignored.kind == CaptureActionKind.IGNORE
    assert ready is True
    assert submitted.kind == CaptureActionKind.SUBMITTED
    assert submitted.prompt == "check tests"
    assert session.is_capturing is False


def test_marker_capture_buffers_speech_and_submits_without_markers() -> None:
    session = MarkerCaptureSession(
        CaptureConfig(
            wake_word="codex",
            start_phrase="start command",
            submit_phrase="send command",
            silence_timeout_seconds=5.0,
        )
    )
    session.handle_text("codex start command", now=0.0)
    session.mark_ready(now=0.5)
    buffered = session.handle_text("check tests", now=1.0)
    submitted = session.handle_text("send command", now=3.0)

    assert buffered.kind == CaptureActionKind.BUFFERED
    assert buffered.buffer_text == "check tests"
    assert submitted.kind == CaptureActionKind.SUBMITTED
    assert submitted.prompt == "check tests"
    assert submitted.reply is None
    assert session.is_capturing is False


def test_marker_capture_ignores_remainder_after_start_until_ready() -> None:
    session = MarkerCaptureSession(
        CaptureConfig(
            wake_word="tim",
            start_phrase="start command",
            submit_phrase="send command",
        )
    )

    action = session.handle_text("Tim, start command. Hello, how are you? Tim, send command.", now=0.0)

    assert action.kind == CaptureActionKind.STARTED
    assert action.buffer_text is None
    assert session.is_capturing is True
    assert session.deadline is None


def test_marker_capture_submits_text_before_marker_while_capturing() -> None:
    session = MarkerCaptureSession(
        CaptureConfig(
            wake_word="tim",
            start_phrase="start command",
            submit_phrase="send command",
        )
    )
    session.handle_text("Tim, start command.", now=0.0)
    session.mark_ready(now=0.5)

    action = session.handle_text("Hello, how are you? Tim, send command.", now=1.0)

    assert action.kind == CaptureActionKind.SUBMITTED
    assert action.prompt == "hello how are you"
    assert session.is_capturing is False


def test_marker_capture_does_not_capture_remainder_after_start_phrase() -> None:
    session = MarkerCaptureSession(CaptureConfig(wake_word="codex", start_phrase="start command"))

    action = session.handle_text("codex start command check README", now=0.0)

    assert action.kind == CaptureActionKind.STARTED
    assert action.buffer_text is None


def test_marker_capture_cancel_clears_buffer() -> None:
    session = MarkerCaptureSession(CaptureConfig(cancel_phrase="cancel command"))
    session.handle_text("start command", now=0.0)
    session.mark_ready(now=0.5)
    session.handle_text("check tests", now=1.0)

    action = session.handle_text("cancel command", now=2.0)

    assert action.kind == CaptureActionKind.CANCELLED
    assert action.reason == "explicit_cancel"
    assert action.reply is None
    assert session.is_capturing is False


def test_marker_capture_default_cancel_phrase_is_single_word_cancel() -> None:
    session = MarkerCaptureSession(CaptureConfig())
    session.handle_text("start command", now=0.0)
    session.mark_ready(now=0.5)
    session.handle_text("check tests", now=1.0)

    action = session.handle_text("cancel", now=2.0)

    assert action.kind == CaptureActionKind.CANCELLED
    assert action.reason == "explicit_cancel"
    assert session.is_capturing is False


def test_marker_capture_ignores_repeated_start_marker_while_capturing() -> None:
    session = MarkerCaptureSession(CaptureConfig())
    session.handle_text("start command", now=0.0)
    session.mark_ready(now=0.5)

    repeated = session.handle_text("start command", now=1.0)
    submitted = session.handle_text("check tests send command", now=2.0)

    assert repeated.kind == CaptureActionKind.IGNORE
    assert submitted.kind == CaptureActionKind.SUBMITTED
    assert submitted.prompt == "check tests"


def test_marker_capture_ignores_transcript_containing_repeated_start_marker_while_capturing() -> None:
    session = MarkerCaptureSession(CaptureConfig())
    session.handle_text("start command", now=0.0)
    session.mark_ready(now=0.5)

    repeated = session.handle_text("well it did not find anything start command", now=1.0)
    submitted = session.handle_text("check tests send command", now=2.0)

    assert repeated.kind == CaptureActionKind.IGNORE
    assert submitted.kind == CaptureActionKind.SUBMITTED
    assert submitted.prompt == "check tests"


def test_marker_capture_cancel_accepts_cancel_word_with_trailing_text() -> None:
    session = MarkerCaptureSession(CaptureConfig())
    session.handle_text("start command", now=0.0)
    session.mark_ready(now=0.5)
    session.handle_text("check tests", now=1.0)

    action = session.handle_text("cancel now", now=2.0)

    assert action.kind == CaptureActionKind.CANCELLED
    assert action.reason == "explicit_cancel"
    assert session.is_capturing is False


def test_marker_capture_auto_cancels_after_silence_timeout() -> None:
    session = MarkerCaptureSession(CaptureConfig(silence_timeout_seconds=5.0))
    session.handle_text("start command", now=10.0)
    session.mark_ready(now=10.5)
    session.handle_text("check tests", now=12.0)

    before_timeout = session.check_timeout(now=16.9)
    timeout = session.check_timeout(now=17.0)

    assert before_timeout.kind == CaptureActionKind.IGNORE
    assert timeout.kind == CaptureActionKind.CANCELLED
    assert timeout.reason == "silence_timeout"
    assert timeout.reply is None
    assert session.is_capturing is False


def test_marker_capture_timeout_starts_after_ready_signal() -> None:
    session = MarkerCaptureSession(CaptureConfig(silence_timeout_seconds=5.0))
    session.handle_text("start command", now=10.0)

    pending_timeout = session.check_timeout(now=20.0)
    ready = session.mark_ready(now=20.0)
    before_timeout = session.check_timeout(now=24.9)
    timeout = session.check_timeout(now=25.0)

    assert pending_timeout.kind == CaptureActionKind.IGNORE
    assert ready is True
    assert before_timeout.kind == CaptureActionKind.IGNORE
    assert timeout.kind == CaptureActionKind.CANCELLED
