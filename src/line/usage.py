from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from line.time_utils import utc_now_iso


@dataclass(frozen=True)
class UsageRecord:
    created_at: str
    kind: str
    seconds: float = 0.0
    chars: int = 0


class UsageLog:
    def __init__(self, path: Path) -> None:
        self._path = path

    def record_seconds(
        self,
        kind: str,
        seconds: float,
        *,
        created_at: str | None = None,
    ) -> UsageRecord:
        return self._append(
            UsageRecord(
                created_at=created_at or utc_now_iso(),
                kind=kind,
                seconds=seconds,
                chars=0,
            )
        )

    def record_chars(
        self,
        kind: str,
        chars: int,
        *,
        created_at: str | None = None,
    ) -> UsageRecord:
        return self._append(
            UsageRecord(
                created_at=created_at or utc_now_iso(),
                kind=kind,
                seconds=0.0,
                chars=chars,
            )
        )

    def read_all(self) -> list[UsageRecord]:
        if not self._path.exists():
            return []
        records: list[UsageRecord] = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            data = json.loads(line)
            records.append(
                UsageRecord(
                    created_at=data["created_at"],
                    kind=data["kind"],
                    seconds=float(data.get("seconds", 0.0)),
                    chars=int(data.get("chars", 0)),
                )
            )
        return records

    def monthly_summary(self, month: str) -> dict[str, dict[str, float | int]]:
        summary: dict[str, dict[str, float | int]] = {}
        for record in self.read_all():
            if not record.created_at.startswith(f"{month}-"):
                continue
            totals = summary.setdefault(record.kind, {"seconds": 0.0, "chars": 0})
            totals["seconds"] = float(totals["seconds"]) + record.seconds
            totals["chars"] = int(totals["chars"]) + record.chars
        return summary

    def _append(self, record: UsageRecord) -> UsageRecord:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record.__dict__, ensure_ascii=False, sort_keys=True) + "\n")
        return record
