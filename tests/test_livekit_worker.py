import pickle

from line.intent import IntentRouter
from line.livekit_worker import _livekit_entrypoint, _route_text
from line.task_queue import TaskQueue


def test_livekit_entrypoint_is_pickleable_for_spawn_executor() -> None:
    assert pickle.loads(pickle.dumps(_livekit_entrypoint)) is _livekit_entrypoint


def test_route_text_enqueues_dispatch(tmp_path) -> None:
    queue = TaskQueue(tmp_path / "tasks.jsonl")

    reply = _route_text(
        router=IntentRouter(),
        queue=queue,
        text="Ask Codex to check the queue.",
    )

    assert reply == "Accepted, sent Codex task: check the queue."
    assert queue.list_tasks()[0].task_text == "check the queue"


def test_route_text_returns_queue_status(tmp_path) -> None:
    queue = TaskQueue(tmp_path / "tasks.jsonl")
    queue.add_task(task_text="check the queue", source_text="Ask Codex to check the queue")

    reply = _route_text(router=IntentRouter(), queue=queue, text="status")

    assert reply == "Codex queue has 1 task."
