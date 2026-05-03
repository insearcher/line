from __future__ import annotations

from line.agent_runs import AgentRunStatus, AgentRunStore


def test_agent_run_store_tracks_done_lifecycle(tmp_path) -> None:
    store = AgentRunStore(tmp_path / "agent_runs.jsonl")

    queued = store.create_queued(
        backend="claude-cli",
        model="haiku",
        prompt="проверь тесты",
        created_at="2026-05-02T10:00:00+00:00",
    )
    running = store.mark_running(queued.id, started_at="2026-05-02T10:00:03+00:00")
    done = store.mark_done(
        queued.id,
        reply="Тесты прошли.",
        finished_at="2026-05-02T10:00:28+00:00",
    )

    assert queued.status == AgentRunStatus.QUEUED
    assert running.status == AgentRunStatus.RUNNING
    assert done.status == AgentRunStatus.DONE
    assert done.reply == "Тесты прошли."
    assert done.error is None
    assert done.duration_seconds == 25.0
    assert store.list_runs() == [done]


def test_agent_run_store_tracks_failed_lifecycle(tmp_path) -> None:
    store = AgentRunStore(tmp_path / "agent_runs.jsonl")

    run = store.create_queued(
        backend="claude-cli",
        model="haiku",
        prompt="сломайся",
        created_at="2026-05-02T10:00:00+00:00",
    )
    store.mark_running(run.id, started_at="2026-05-02T10:00:01+00:00")
    failed = store.mark_failed(
        run.id,
        error="Claude CLI failed",
        finished_at="2026-05-02T10:00:04+00:00",
    )

    assert failed.status == AgentRunStatus.FAILED
    assert failed.reply is None
    assert failed.error == "Claude CLI failed"
    assert failed.duration_seconds == 3.0


def test_agent_run_store_returns_newest_first(tmp_path) -> None:
    store = AgentRunStore(tmp_path / "agent_runs.jsonl")
    first = store.create_queued(
        backend="claude-cli",
        model="haiku",
        prompt="первая",
        created_at="2026-05-02T10:00:00+00:00",
    )
    second = store.create_queued(
        backend="claude-cli",
        model="haiku",
        prompt="вторая",
        created_at="2026-05-02T10:00:05+00:00",
    )

    assert [run.id for run in store.list_runs_newest_first()] == [second.id, first.id]
