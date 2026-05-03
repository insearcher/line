from line.events import EventLog
from line.routing_service import route_transcript
from line.task_queue import TaskQueue


def test_route_transcript_records_dispatch_task_and_events(tmp_path) -> None:
    queue = TaskQueue(tmp_path / "tasks.jsonl")
    events = EventLog(tmp_path / "events.jsonl")

    result = route_transcript(
        text="Попроси Кодекс проверить очередь.",
        queue=queue,
        events=events,
    )

    assert result.intent == "dispatch"
    assert result.reply == "Принял, отправил Codex задачу: проверить очередь."
    assert result.task is not None
    assert queue.list_tasks()[0].task_text == "проверить очередь"
    assert [record.type for record in events.read_all()] == [
        "transcript.final",
        "route.result",
        "task.queued",
    ]


def test_route_transcript_records_status_without_queueing_task(tmp_path) -> None:
    queue = TaskQueue(tmp_path / "tasks.jsonl")
    events = EventLog(tmp_path / "events.jsonl")
    queue.add_task(task_text="проверить очередь", source_text="Попроси Кодекс проверить очередь")

    result = route_transcript(text="статус", queue=queue, events=events)

    assert result.intent == "status"
    assert result.reply == "В очереди Codex 1 задача."
    assert result.task is None
    assert len(queue.list_tasks()) == 1
    assert [record.type for record in events.read_all()] == ["transcript.final", "route.result"]
