from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
import json
from pathlib import Path
from uuid import uuid4


class TaskStatus(StrEnum):
    PENDING = "pending"
    DISPATCHED = "dispatched"
    DONE = "done"
    ABANDONED = "abandoned"


@dataclass(frozen=True)
class TaskRecord:
    id: str
    created_at: str
    task_text: str
    source_text: str
    status: TaskStatus = TaskStatus.PENDING

    def to_json(self) -> str:
        payload = asdict(self)
        payload["status"] = self.status.value
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_json(cls, line: str) -> TaskRecord:
        payload = json.loads(line)
        payload["status"] = TaskStatus(payload["status"])
        return cls(**payload)


class TaskQueue:
    def __init__(self, path: Path) -> None:
        self.path = path

    def add_task(self, task_text: str, source_text: str) -> TaskRecord:
        record = TaskRecord(
            id=str(uuid4()),
            created_at=datetime.now(UTC).isoformat(timespec="seconds"),
            task_text=task_text,
            source_text=source_text,
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(record.to_json())
            stream.write("\n")
        return record

    def list_tasks(self) -> list[TaskRecord]:
        if not self.path.exists():
            return []
        records: list[TaskRecord] = []
        with self.path.open("r", encoding="utf-8") as stream:
            for line in stream:
                stripped = line.strip()
                if stripped:
                    records.append(TaskRecord.from_json(stripped))
        return records

    def status_summary(self) -> str:
        pending_count = sum(1 for task in self.list_tasks() if task.status == TaskStatus.PENDING)
        if pending_count == 0:
            return "Очередь Codex пуста."
        if pending_count == 1:
            return "В очереди Codex 1 задача."
        return f"В очереди Codex {pending_count} задачи."
