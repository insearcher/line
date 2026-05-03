from __future__ import annotations

from line.capture import CaptureActionKind, CaptureConfig, MarkerCaptureSession


def test_marker_capture_ignores_speech_without_wake_start() -> None:
    session = MarkerCaptureSession(CaptureConfig(wake_word="кодекс", start_phrase="начало"))

    action = session.handle_text("я разговариваю с человеком", now=0.0)

    assert action.kind == CaptureActionKind.IGNORE
    assert session.is_capturing is False


def test_marker_capture_starts_only_with_wake_and_start_phrase() -> None:
    session = MarkerCaptureSession(CaptureConfig(wake_word="кодекс", start_phrase="начало"))

    action = session.handle_text("Кодекс начало", now=10.0)

    assert action.kind == CaptureActionKind.STARTED
    assert action.reply is None
    assert session.is_capturing is True
    assert session.deadline is None


def test_marker_capture_waits_for_ready_before_buffering_text() -> None:
    session = MarkerCaptureSession(
        CaptureConfig(
            wake_word="",
            start_phrase="запись",
            submit_phrase="конец",
        )
    )

    started = session.handle_text("Запись. Привет, ты меня слышишь? Конец.", now=10.0)
    ignored = session.handle_text("этот текст пришел до сигнала", now=10.5)
    ready = session.mark_ready(now=11.0)
    submitted = session.handle_text("Проверь тесты. Конец.", now=12.0)

    assert started.kind == CaptureActionKind.STARTED
    assert started.buffer_text is None
    assert ignored.kind == CaptureActionKind.IGNORE
    assert ready is True
    assert submitted.kind == CaptureActionKind.SUBMITTED
    assert submitted.prompt == "проверь тесты"
    assert session.is_capturing is False


def test_marker_capture_buffers_speech_and_submits_without_markers() -> None:
    session = MarkerCaptureSession(
        CaptureConfig(
            wake_word="кодекс",
            start_phrase="начало",
            submit_phrase="конец команды",
            silence_timeout_seconds=5.0,
        )
    )
    session.handle_text("кодекс начало", now=0.0)
    session.mark_ready(now=0.5)
    buffered = session.handle_text("проверь тесты", now=1.0)
    submitted = session.handle_text("конец команды", now=3.0)

    assert buffered.kind == CaptureActionKind.BUFFERED
    assert buffered.buffer_text == "проверь тесты"
    assert submitted.kind == CaptureActionKind.SUBMITTED
    assert submitted.prompt == "проверь тесты"
    assert submitted.reply is None
    assert session.is_capturing is False


def test_marker_capture_ignores_remainder_after_start_until_ready() -> None:
    session = MarkerCaptureSession(
        CaptureConfig(
            wake_word="тим",
            start_phrase="начало",
            submit_phrase="конец",
        )
    )

    action = session.handle_text("Тим, начало. Привет, как дела? Тим, конец.", now=0.0)

    assert action.kind == CaptureActionKind.STARTED
    assert action.buffer_text is None
    assert session.is_capturing is True
    assert session.deadline is None


def test_marker_capture_submits_text_before_marker_while_capturing() -> None:
    session = MarkerCaptureSession(
        CaptureConfig(
            wake_word="тим",
            start_phrase="начало",
            submit_phrase="конец",
        )
    )
    session.handle_text("Тим, начало.", now=0.0)
    session.mark_ready(now=0.5)

    action = session.handle_text("Привет, как дела? Тим, конец.", now=1.0)

    assert action.kind == CaptureActionKind.SUBMITTED
    assert action.prompt == "привет как дела"
    assert session.is_capturing is False


def test_marker_capture_does_not_capture_remainder_after_start_phrase() -> None:
    session = MarkerCaptureSession(CaptureConfig(wake_word="кодекс", start_phrase="начало"))

    action = session.handle_text("кодекс начало проверь README", now=0.0)

    assert action.kind == CaptureActionKind.STARTED
    assert action.buffer_text is None


def test_marker_capture_cancel_clears_buffer() -> None:
    session = MarkerCaptureSession(CaptureConfig(cancel_phrase="отмена команды"))
    session.handle_text("запись", now=0.0)
    session.mark_ready(now=0.5)
    session.handle_text("проверь тесты", now=1.0)

    action = session.handle_text("отмена команды", now=2.0)

    assert action.kind == CaptureActionKind.CANCELLED
    assert action.reason == "explicit_cancel"
    assert action.reply is None
    assert session.is_capturing is False


def test_marker_capture_default_cancel_phrase_is_single_word_otmena() -> None:
    session = MarkerCaptureSession(CaptureConfig())
    session.handle_text("запись", now=0.0)
    session.mark_ready(now=0.5)
    session.handle_text("проверь тесты", now=1.0)

    action = session.handle_text("отмена", now=2.0)

    assert action.kind == CaptureActionKind.CANCELLED
    assert action.reason == "explicit_cancel"
    assert session.is_capturing is False


def test_marker_capture_ignores_repeated_start_marker_while_capturing() -> None:
    session = MarkerCaptureSession(CaptureConfig())
    session.handle_text("запись", now=0.0)
    session.mark_ready(now=0.5)

    repeated = session.handle_text("запись", now=1.0)
    submitted = session.handle_text("проверь тесты конец", now=2.0)

    assert repeated.kind == CaptureActionKind.IGNORE
    assert submitted.kind == CaptureActionKind.SUBMITTED
    assert submitted.prompt == "проверь тесты"


def test_marker_capture_ignores_transcript_containing_repeated_start_marker_while_capturing() -> None:
    session = MarkerCaptureSession(CaptureConfig())
    session.handle_text("запись", now=0.0)
    session.mark_ready(now=0.5)

    repeated = session.handle_text("ну что он ничего не нашел запись", now=1.0)
    submitted = session.handle_text("проверь тесты конец", now=2.0)

    assert repeated.kind == CaptureActionKind.IGNORE
    assert submitted.kind == CaptureActionKind.SUBMITTED
    assert submitted.prompt == "проверь тесты"


def test_marker_capture_cancel_accepts_clipped_otmena() -> None:
    session = MarkerCaptureSession(CaptureConfig())
    session.handle_text("запись", now=0.0)
    session.mark_ready(now=0.5)
    session.handle_text("проверь тесты", now=1.0)

    action = session.handle_text("мена говорю", now=2.0)

    assert action.kind == CaptureActionKind.CANCELLED
    assert action.reason == "explicit_cancel"
    assert session.is_capturing is False


def test_marker_capture_auto_cancels_after_silence_timeout() -> None:
    session = MarkerCaptureSession(CaptureConfig(silence_timeout_seconds=5.0))
    session.handle_text("запись", now=10.0)
    session.mark_ready(now=10.5)
    session.handle_text("проверь тесты", now=12.0)

    before_timeout = session.check_timeout(now=16.9)
    timeout = session.check_timeout(now=17.0)

    assert before_timeout.kind == CaptureActionKind.IGNORE
    assert timeout.kind == CaptureActionKind.CANCELLED
    assert timeout.reason == "silence_timeout"
    assert timeout.reply is None
    assert session.is_capturing is False


def test_marker_capture_timeout_starts_after_ready_signal() -> None:
    session = MarkerCaptureSession(CaptureConfig(silence_timeout_seconds=5.0))
    session.handle_text("запись", now=10.0)

    pending_timeout = session.check_timeout(now=20.0)
    ready = session.mark_ready(now=20.0)
    before_timeout = session.check_timeout(now=24.9)
    timeout = session.check_timeout(now=25.0)

    assert pending_timeout.kind == CaptureActionKind.IGNORE
    assert ready is True
    assert before_timeout.kind == CaptureActionKind.IGNORE
    assert timeout.kind == CaptureActionKind.CANCELLED
