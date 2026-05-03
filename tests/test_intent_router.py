from line.intent import IntentKind, IntentRouter


def test_dispatch_intent_extracts_codex_task() -> None:
    router = IntentRouter()

    intent = router.classify("Попроси Codex добавить тесты для очереди задач")

    assert intent.kind == IntentKind.DISPATCH
    assert intent.task_text == "добавить тесты для очереди задач"
    assert intent.should_enqueue is True
    assert "отправил Codex" in intent.spoken_reply


def test_cancel_intent_is_not_enqueued() -> None:
    router = IntentRouter()

    intent = router.classify("Отмена, не отправляй это в кодекс")

    assert intent.kind == IntentKind.CANCEL
    assert intent.task_text is None
    assert intent.should_enqueue is False
    assert "отменил" in intent.spoken_reply.lower()


def test_status_intent_is_not_enqueued() -> None:
    router = IntentRouter()

    intent = router.classify("Что там со статусом?")

    assert intent.kind == IntentKind.STATUS
    assert intent.should_enqueue is False
    assert "статус" in intent.spoken_reply.lower()


def test_plain_text_falls_back_to_chat() -> None:
    router = IntentRouter()

    intent = router.classify("Привет, ты меня слышишь?")

    assert intent.kind == IntentKind.CHAT
    assert intent.should_enqueue is False
    assert "слышу" in intent.spoken_reply.lower()
