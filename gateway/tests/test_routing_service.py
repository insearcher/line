from line.events import EventLog
from line.routing_service import route_transcript
from line.task_queue import TaskQueue


def test_route_transcript_records_dispatch_task_and_events(tmp_path) -> None:
    queue = TaskQueue(tmp_path / "tasks.jsonl")
    events = EventLog(tmp_path / "events.jsonl")

    result = route_transcript(
        text="Ask Codex to check the queue.",
        queue=queue,
        events=events,
    )

    assert result.intent == "dispatch"
    assert result.reply == "Accepted, sent Codex task: check the queue."
    assert result.task is not None
    assert queue.list_tasks()[0].task_text == "check the queue"
    assert [record.type for record in events.read_all()] == [
        "transcript.final",
        "route.result",
        "task.queued",
    ]


def test_route_transcript_records_status_without_queueing_task(tmp_path) -> None:
    queue = TaskQueue(tmp_path / "tasks.jsonl")
    events = EventLog(tmp_path / "events.jsonl")
    queue.add_task(task_text="check the queue", source_text="Ask Codex to check the queue")

    result = route_transcript(text="status", queue=queue, events=events)

    assert result.intent == "status"
    assert result.reply == "Codex queue has 1 task."
    assert result.task is None
    assert len(queue.list_tasks()) == 1
    assert [record.type for record in events.read_all()] == ["transcript.final", "route.result"]
