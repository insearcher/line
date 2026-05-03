from pathlib import Path

from line.task_queue import TaskQueue, TaskStatus


def test_add_task_persists_pending_record(tmp_path: Path) -> None:
    queue = TaskQueue(tmp_path / "tasks.jsonl")

    record = queue.add_task(
        task_text="добавить dry-run команду",
        source_text="попроси Codex добавить dry-run команду",
    )

    assert record.status == TaskStatus.PENDING
    assert record.task_text == "добавить dry-run команду"
    assert record.source_text == "попроси Codex добавить dry-run команду"

    loaded = queue.list_tasks()
    assert loaded == [record]


def test_status_summary_counts_pending_tasks(tmp_path: Path) -> None:
    queue = TaskQueue(tmp_path / "tasks.jsonl")
    queue.add_task(task_text="первая задача", source_text="попроси Codex первая задача")
    queue.add_task(task_text="вторая задача", source_text="попроси Codex вторая задача")

    summary = queue.status_summary()

    assert summary == "В очереди Codex 2 задачи."
