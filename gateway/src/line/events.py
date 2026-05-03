from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from line.time_utils import utc_now_iso


@dataclass(frozen=True)
class EventRecord:
    id: str
    created_at: str
    type: str
    payload: dict[str, Any]


class EventLog:
    def __init__(self, path: Path) -> None:
        self._path = path

    def append(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        created_at: str | None = None,
    ) -> EventRecord:
        record = EventRecord(
            id=str(uuid4()),
            created_at=created_at or utc_now_iso(),
            type=event_type,
            payload=payload,
        )
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record.__dict__, ensure_ascii=False, sort_keys=True) + "\n")
        return record

    def read_all(self) -> list[EventRecord]:
        if not self._path.exists():
            return []
        records: list[EventRecord] = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            data = json.loads(line)
            records.append(
                EventRecord(
                    id=data["id"],
                    created_at=data["created_at"],
                    type=data["type"],
                    payload=dict(data["payload"]),
                )
            )
        return records

    def read_after(self, after_id: str) -> list[EventRecord]:
        records = self.read_all()
        for index, record in enumerate(records):
            if record.id == after_id:
                return records[index + 1 :]
        return records
