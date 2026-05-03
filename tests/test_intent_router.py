from line.intent import IntentKind, IntentRouter


def test_dispatch_intent_extracts_codex_task() -> None:
    router = IntentRouter()

    intent = router.classify("Ask Codex to add tests for the task queue")

    assert intent.kind == IntentKind.DISPATCH
    assert intent.task_text == "add tests for the task queue"
    assert intent.should_enqueue is True
    assert "sent Codex task" in intent.spoken_reply


def test_cancel_intent_is_not_enqueued() -> None:
    router = IntentRouter()

    intent = router.classify("Cancel, do not send this to codex")

    assert intent.kind == IntentKind.CANCEL
    assert intent.task_text is None
    assert intent.should_enqueue is False
    assert "cancelled" in intent.spoken_reply.lower()


def test_status_intent_is_not_enqueued() -> None:
    router = IntentRouter()

    intent = router.classify("What is happening with the task?")

    assert intent.kind == IntentKind.STATUS
    assert intent.should_enqueue is False
    assert "status" in intent.spoken_reply.lower()


def test_plain_text_falls_back_to_chat() -> None:
    router = IntentRouter()

    intent = router.classify("Hello, can you hear me?")

    assert intent.kind == IntentKind.CHAT
    assert intent.should_enqueue is False
    assert "hear you" in intent.spoken_reply.lower()
