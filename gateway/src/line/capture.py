from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re


class CaptureMode(StrEnum):
    DIRECT = "direct"
    MARKERS = "markers"


class CaptureActionKind(StrEnum):
    IGNORE = "ignore"
    STARTED = "started"
    BUFFERED = "buffered"
    SUBMITTED = "submitted"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class CaptureConfig:
    mode: CaptureMode = CaptureMode.DIRECT
    wake_word: str = ""
    start_phrase: str = "start command"
    submit_phrase: str = "send command"
    cancel_phrase: str = "cancel"
    silence_timeout_seconds: float = 20.0


@dataclass(frozen=True)
class CaptureAction:
    kind: CaptureActionKind
    text: str
    prompt: str | None = None
    buffer_text: str | None = None
    reply: str | None = None
    reason: str | None = None


class MarkerCaptureSession:
    def __init__(self, config: CaptureConfig) -> None:
        self.config = config
        self._buffer: list[str] = []
        self._deadline: float | None = None
        self._waiting_for_ready = False

    @property
    def is_capturing(self) -> bool:
        return self._waiting_for_ready or self._deadline is not None

    @property
    def deadline(self) -> float | None:
        return self._deadline

    def mark_ready(self, *, now: float) -> bool:
        if not self._waiting_for_ready:
            return False
        self._waiting_for_ready = False
        self._deadline = now + self.config.silence_timeout_seconds
        return True

    def reset(self) -> bool:
        was_active = self.is_capturing or bool(self._buffer)
        self._buffer = []
        self._deadline = None
        self._waiting_for_ready = False
        return was_active

    def handle_text(self, text: str, *, now: float) -> CaptureAction:
        normalized = normalize_marker_text(text)
        if not normalized:
            return CaptureAction(kind=CaptureActionKind.IGNORE, text=text)

        if self._waiting_for_ready:
            return CaptureAction(kind=CaptureActionKind.IGNORE, text=text)

        if not self.is_capturing:
            start_split = _split_on_phrase(normalized, self._start_marker())
            if start_split is None:
                return CaptureAction(kind=CaptureActionKind.IGNORE, text=text)
            self._buffer = []
            self._deadline = None
            self._waiting_for_ready = True
            return CaptureAction(kind=CaptureActionKind.STARTED, text=text)

        return self._capture_text(normalized, text=text, now=now, started=False)

    def handle_cancel_text(self, text: str) -> CaptureAction:
        normalized = normalize_marker_text(text)
        if not normalized:
            return CaptureAction(kind=CaptureActionKind.IGNORE, text=text)
        if self._find_control(normalized, kinds={CaptureActionKind.CANCELLED}) is None:
            return CaptureAction(kind=CaptureActionKind.IGNORE, text=text)
        return self._cancel(text=text, reason="explicit_cancel", reply="Command cancelled.")

    def check_timeout(self, *, now: float) -> CaptureAction:
        if self._deadline is None or now < self._deadline:
            return CaptureAction(kind=CaptureActionKind.IGNORE, text="")
        return self._cancel(text="", reason="silence_timeout", reply="Command cancelled after silence.")

    def _start_marker(self) -> str:
        wake = normalize_marker_text(self.config.wake_word)
        start = normalize_marker_text(self.config.start_phrase)
        if wake and start.startswith(f"{wake} "):
            return start
        return f"{wake} {start}".strip()

    def _capture_text(self, normalized: str, *, text: str, now: float, started: bool) -> CaptureAction:
        start_split = _split_on_phrase(normalized, self._start_marker())
        if start_split is not None:
            return CaptureAction(kind=CaptureActionKind.IGNORE, text=text)

        control = self._find_control(normalized)
        if control is not None:
            if control.before:
                self._buffer.append(control.before)
            if control.kind == CaptureActionKind.CANCELLED:
                return self._cancel(text=text, reason="explicit_cancel", reply="Command cancelled.")
            return self._submit(text=text)

        if normalized:
            self._buffer.append(normalized)
            self._deadline = now + self.config.silence_timeout_seconds

        if started:
            return CaptureAction(
                kind=CaptureActionKind.STARTED,
                text=text,
                buffer_text=" ".join(self._buffer) or None,
            )
        return CaptureAction(
            kind=CaptureActionKind.BUFFERED,
            text=text,
            buffer_text=" ".join(self._buffer),
        )

    def _submit(self, *, text: str) -> CaptureAction:
        prompt = " ".join(self._buffer).strip()
        self._buffer = []
        self._deadline = None
        if not prompt:
            return CaptureAction(
                kind=CaptureActionKind.CANCELLED,
                text=text,
                reason="empty_command",
                reply="Empty command, cancelled.",
            )
        return CaptureAction(
            kind=CaptureActionKind.SUBMITTED,
            text=text,
            prompt=prompt,
        )

    def _find_control(
        self,
        normalized: str,
        *,
        kinds: set[CaptureActionKind] | None = None,
    ) -> _PhraseMatch | None:
        matches: list[_PhraseMatch] = []
        for kind, phrase in (
            (CaptureActionKind.CANCELLED, self.config.cancel_phrase),
            (CaptureActionKind.SUBMITTED, self.config.submit_phrase),
        ):
            if kinds is not None and kind not in kinds:
                continue
            for marker in self._control_markers(phrase):
                match = _split_on_phrase(normalized, marker, kind=kind)
                if match is not None:
                    matches.append(match)
        if not matches:
            return None
        return min(matches, key=lambda match: (match.start, -(match.end - match.start)))

    def _control_markers(self, phrase: str) -> list[str]:
        wake = normalize_marker_text(self.config.wake_word)
        marker = normalize_marker_text(phrase)
        if not marker:
            return []
        markers = [marker, *_marker_aliases(marker)]
        candidates: list[str] = []
        for marker_variant in markers:
            prefixed = f"{wake} {marker_variant}".strip()
            if wake and not marker_variant.startswith(f"{wake} "):
                candidates.extend([prefixed, marker_variant])
            else:
                candidates.append(marker_variant)
        return list(dict.fromkeys(candidates))

    def _cancel(self, *, text: str, reason: str, reply: str) -> CaptureAction:
        self._buffer = []
        self._deadline = None
        self._waiting_for_ready = False
        return CaptureAction(
            kind=CaptureActionKind.CANCELLED,
            text=text,
            reason=reason,
        )


def normalize_marker_text(text: str) -> str:
    lowered = text.lower()
    unpunctuated = re.sub(r"[^\w\s]+", " ", lowered)
    return re.sub(r"\s+", " ", unpunctuated).strip()


def _marker_aliases(marker: str) -> list[str]:
    del marker
    return []


@dataclass(frozen=True)
class _PhraseMatch:
    before: str
    after: str
    start: int
    end: int
    kind: CaptureActionKind | None = None


def _split_on_phrase(text: str, phrase: str, *, kind: CaptureActionKind | None = None) -> _PhraseMatch | None:
    marker = normalize_marker_text(phrase)
    if not marker:
        return None
    padded_text = f" {text} "
    padded_marker = f" {marker} "
    start = padded_text.find(padded_marker)
    if start == -1:
        return None
    end = start + len(marker)
    return _PhraseMatch(
        before=text[:start].strip(),
        after=text[end:].strip(),
        start=start,
        end=end,
        kind=kind,
    )
