from pathlib import Path

from line.task_queue import TaskQueue, TaskStatus


def test_add_task_persists_pending_record(tmp_path: Path) -> None:
    queue = TaskQueue(tmp_path / "tasks.jsonl")

    record = queue.add_task(
        task_text="add a dry-run command",
        source_text="ask Codex add a dry-run command",
    )

    assert record.status == TaskStatus.PENDING
    assert record.task_text == "add a dry-run command"
    assert record.source_text == "ask Codex add a dry-run command"

    loaded = queue.list_tasks()
    assert loaded == [record]


def test_status_summary_counts_pending_tasks(tmp_path: Path) -> None:
    queue = TaskQueue(tmp_path / "tasks.jsonl")
    queue.add_task(task_text="first task", source_text="ask Codex first task")
    queue.add_task(task_text="second task", source_text="ask Codex second task")

    summary = queue.status_summary()

    assert summary == "Codex queue has 2 tasks."
