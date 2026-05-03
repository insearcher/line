from __future__ import annotations

from dataclasses import dataclass

from line.events import EventLog
from line.intent import IntentKind, IntentRouter
from line.task_queue import TaskQueue, TaskRecord


@dataclass(frozen=True)
class RouteResult:
    intent: str
    text: str
    reply: str
    task: TaskRecord | None


def route_transcript(text: str, queue: TaskQueue, events: EventLog | None = None) -> RouteResult:
    router = IntentRouter()
    intent = router.classify(text)
    task: TaskRecord | None = None
    reply = intent.spoken_reply

    if events is not None:
        events.append(
            "transcript.final",
            {
                "text": intent.original_text,
                "normalized_text": intent.normalized_text,
            },
        )

    if intent.kind == IntentKind.STATUS:
        reply = queue.status_summary()
    elif intent.should_enqueue and intent.task_text:
        task = queue.add_task(task_text=intent.task_text, source_text=intent.original_text)

    result = RouteResult(
        intent=intent.kind.value,
        text=intent.original_text,
        reply=reply,
        task=task,
    )

    if events is not None:
        events.append(
            "route.result",
            {
                "intent": result.intent,
                "reply": result.reply,
                "task_id": result.task.id if result.task else None,
            },
        )
        if task is not None:
            events.append(
                "task.queued",
                {
                    "id": task.id,
                    "task_text": task.task_text,
                    "source_text": task.source_text,
                },
            )

    return result
