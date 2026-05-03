from line.events import EventLog


def test_event_log_appends_and_reads_records_in_order(tmp_path) -> None:
    log = EventLog(tmp_path / "events.jsonl")

    first = log.append("transcript.final", {"text": "Ask Codex to check the queue"})
    second = log.append("route.reply", {"reply": "Accepted"})

    records = log.read_all()
    assert [record.id for record in records] == [first.id, second.id]
    assert [record.type for record in records] == ["transcript.final", "route.reply"]
    assert records[0].payload == {"text": "Ask Codex to check the queue"}
    assert records[1].payload == {"reply": "Accepted"}
    assert records[0].created_at <= records[1].created_at


def test_event_log_reads_only_records_after_id(tmp_path) -> None:
    log = EventLog(tmp_path / "events.jsonl")

    first = log.append("one", {})
    second = log.append("two", {})
    third = log.append("three", {})

    records = log.read_after(first.id)
    assert [record.id for record in records] == [second.id, third.id]
