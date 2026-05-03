from line.usage import UsageLog


def test_usage_log_aggregates_seconds_and_chars_by_month(tmp_path) -> None:
    log = UsageLog(tmp_path / "usage.jsonl")

    log.record_seconds("audio.received", 10.5, created_at="2026-05-02T10:00:00+00:00")
    log.record_seconds("audio.received", 1.5, created_at="2026-05-02T10:01:00+00:00")
    log.record_seconds("stt.audio", 3.0, created_at="2026-05-02T10:02:00+00:00")
    log.record_chars("tts.chars", 120, created_at="2026-05-02T10:03:00+00:00")
    log.record_seconds("audio.received", 7.0, created_at="2026-06-01T10:00:00+00:00")

    summary = log.monthly_summary("2026-05")

    assert summary["audio.received"]["seconds"] == 12.0
    assert summary["audio.received"]["chars"] == 0
    assert summary["stt.audio"]["seconds"] == 3.0
    assert summary["tts.chars"]["chars"] == 120


def test_usage_log_ignores_other_months(tmp_path) -> None:
    log = UsageLog(tmp_path / "usage.jsonl")

    log.record_seconds("stt.audio", 5.0, created_at="2026-05-31T23:59:00+00:00")
    log.record_seconds("stt.audio", 7.0, created_at="2026-06-01T00:00:00+00:00")

    assert log.monthly_summary("2026-05")["stt.audio"]["seconds"] == 5.0
