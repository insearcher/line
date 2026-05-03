from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime
from enum import StrEnum
import json
from pathlib import Path
from uuid import uuid4

from line.time_utils import utc_now_iso


class AgentRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


@dataclass(frozen=True)
class AgentRunRecord:
    id: str
    created_at: str
    updated_at: str
    backend: str
    model: str
    prompt: str
    status: AgentRunStatus
    started_at: str | None = None
    finished_at: str | None = None
    duration_seconds: float | None = None
    reply: str | None = None
    error: str | None = None

    def to_json(self) -> str:
        payload = asdict(self)
        payload["status"] = self.status.value
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_json(cls, line: str) -> AgentRunRecord:
        payload = json.loads(line)
        payload["status"] = AgentRunStatus(payload["status"])
        return cls(**payload)


class AgentRunStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def create_queued(
        self,
        *,
        backend: str,
        model: str,
        prompt: str,
        created_at: str | None = None,
    ) -> AgentRunRecord:
        now = created_at or utc_now_iso()
        record = AgentRunRecord(
            id=str(uuid4()),
            created_at=now,
            updated_at=now,
            backend=backend,
            model=model,
            prompt=prompt,
            status=AgentRunStatus.QUEUED,
        )
        records = self.list_runs()
        records.append(record)
        self._write_all(records)
        return record

    def mark_running(self, run_id: str, *, started_at: str | None = None) -> AgentRunRecord:
        now = started_at or utc_now_iso()
        return self._update(
            run_id,
            status=AgentRunStatus.RUNNING,
            started_at=now,
            updated_at=now,
        )

    def mark_done(self, run_id: str, *, reply: str, finished_at: str | None = None) -> AgentRunRecord:
        now = finished_at or utc_now_iso()
        return self._finish(
            run_id,
            status=AgentRunStatus.DONE,
            finished_at=now,
            reply=reply,
            error=None,
        )

    def mark_failed(self, run_id: str, *, error: str, finished_at: str | None = None) -> AgentRunRecord:
        now = finished_at or utc_now_iso()
        return self._finish(
            run_id,
            status=AgentRunStatus.FAILED,
            finished_at=now,
            reply=None,
            error=error,
        )

    def list_runs(self) -> list[AgentRunRecord]:
        if not self.path.exists():
            return []
        return [
            AgentRunRecord.from_json(line)
            for line in self.path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def list_runs_newest_first(self) -> list[AgentRunRecord]:
        return sorted(self.list_runs(), key=lambda run: run.created_at, reverse=True)

    def _finish(
        self,
        run_id: str,
        *,
        status: AgentRunStatus,
        finished_at: str,
        reply: str | None,
        error: str | None,
    ) -> AgentRunRecord:
        existing = self._get(run_id)
        started_at = existing.started_at or existing.created_at
        return self._update(
            run_id,
            status=status,
            finished_at=finished_at,
            updated_at=finished_at,
            duration_seconds=_duration_seconds(started_at, finished_at),
            reply=reply,
            error=error,
        )

    def _update(self, run_id: str, **changes) -> AgentRunRecord:
        records = self.list_runs()
        updated: AgentRunRecord | None = None
        next_records: list[AgentRunRecord] = []
        for record in records:
            if record.id == run_id:
                updated = replace(record, **changes)
                next_records.append(updated)
            else:
                next_records.append(record)
        if updated is None:
            raise KeyError(f"Unknown agent run: {run_id}")
        self._write_all(next_records)
        return updated

    def _get(self, run_id: str) -> AgentRunRecord:
        for record in self.list_runs():
            if record.id == run_id:
                return record
        raise KeyError(f"Unknown agent run: {run_id}")

    def _write_all(self, records: list[AgentRunRecord]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as stream:
            for record in records:
                stream.write(record.to_json())
                stream.write("\n")


def _duration_seconds(started_at: str, finished_at: str) -> float:
    started = datetime.fromisoformat(started_at)
    finished = datetime.fromisoformat(finished_at)
    return round((finished - started).total_seconds(), 3)
