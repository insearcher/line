from __future__ import annotations

import json
from pathlib import Path
import threading
from urllib.error import HTTPError
from urllib.request import Request
from urllib.request import urlopen

from line.agent_runs import AgentRunStore
from line.demo_server import DemoServerConfig, create_demo_http_server, reset_demo_state
from line.events import EventLog
from line.pairing import PairingStore
from line.task_queue import TaskQueue
from line.usage import UsageLog

TEST_LIVEKIT_HMAC = "0" * 32
TEST_LIVEKIT_KEY = "test-livekit-value"
TEST_STT_KEY = "test-stt-value"
TEST_TTS_KEY = "test-tts-value"
TEST_TTS_VOICE = "test-tts-voice"
TEST_TTS_MODEL = "test-tts-model"


def test_demo_server_json_endpoints(tmp_path, monkeypatch) -> None:
    _set_voice_env(monkeypatch)

    events_path = tmp_path / "events.jsonl"
    queue_path = tmp_path / "tasks.jsonl"
    usage_path = tmp_path / "usage.jsonl"
    agent_runs_path = tmp_path / "agent_runs.jsonl"
    control_path = tmp_path / "control.jsonl"
    web_dir = tmp_path / "web"
    web_dir.mkdir()
    (web_dir / "index.html").write_text("<html>demo</html>", encoding="utf-8")

    event = EventLog(events_path).append("transcript.final", {"text": "hello"})
    TaskQueue(queue_path).add_task(task_text="check the queue", source_text="Ask Codex to check the queue")
    UsageLog(usage_path).record_seconds("stt.audio", 3.5, created_at="2026-05-02T10:00:00+00:00")
    run = AgentRunStore(agent_runs_path).create_queued(
        backend="haiku",
        model="haiku",
        prompt="check tests",
        created_at="2026-05-02T10:00:01+00:00",
    )

    server = create_demo_http_server(
        DemoServerConfig(
            host="127.0.0.1",
            port=0,
            room="line",
            identity="mac-test",
            web_dir=web_dir,
            events_path=events_path,
            queue_path=queue_path,
            usage_path=usage_path,
            agent_runs_path=agent_runs_path,
            control_path=control_path,
            pairing_state_path=tmp_path / "pairing.json",
        )
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base_url = f"http://127.0.0.1:{server.server_port}"
        auth_header = _pair_phone(base_url, tmp_path / "pairing.json")

        token_payload = _get_json(f"{base_url}/api/token", headers=auth_header)
        assert token_payload["url"] == "wss://example.livekit.cloud"
        assert token_payload["room"] == "line"
        assert token_payload["identity"] == "mac-test"
        assert token_payload["token"]

        ios_token_payload = _get_json(
            f"{base_url}/api/token?room=line-ios&identity=iphone-vad",
            headers=auth_header,
        )
        assert ios_token_payload["url"] == "wss://example.livekit.cloud"
        assert ios_token_payload["room"] == "line-ios"
        assert ios_token_payload["identity"] == "iphone-vad"
        assert ios_token_payload["token"]

        events_payload = _get_json(f"{base_url}/api/events")
        assert events_payload["events"][0]["id"] == event.id
        assert events_payload["events"][0]["payload"] == {"text": "hello"}
        assert events_payload["events"][1]["type"] == "demo.token_requested"
        assert events_payload["events"][1]["payload"]["identity"] == "mac-test"
        assert events_payload["events"][2]["type"] == "demo.token_requested"
        assert events_payload["events"][2]["payload"]["identity"] == "iphone-vad"

        tasks_payload = _get_json(f"{base_url}/api/tasks")
        assert tasks_payload["tasks"][0]["task_text"] == "check the queue"

        usage_payload = _get_json(f"{base_url}/api/usage?month=2026-05")
        assert usage_payload["summary"]["stt.audio"]["seconds"] == 3.5

        agent_runs_payload = _get_json(f"{base_url}/api/agent-runs")
        assert agent_runs_payload["agent_runs"][0]["id"] == run.id
        assert agent_runs_payload["agent_runs"][0]["prompt"] == "check tests"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_demo_server_serves_static_index(tmp_path, monkeypatch) -> None:
    _set_voice_env(monkeypatch)

    web_dir = tmp_path / "web"
    web_dir.mkdir()
    (web_dir / "index.html").write_text("<html>dashboard</html>", encoding="utf-8")
    server = create_demo_http_server(
        DemoServerConfig(
            host="127.0.0.1",
            port=0,
            room="line",
            identity="mac-test",
            web_dir=web_dir,
            events_path=tmp_path / "events.jsonl",
            queue_path=tmp_path / "tasks.jsonl",
            usage_path=tmp_path / "usage.jsonl",
            agent_runs_path=tmp_path / "agent_runs.jsonl",
        )
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        body = urlopen(f"http://127.0.0.1:{server.server_port}/", timeout=5).read().decode("utf-8")
        assert "dashboard" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_reset_demo_state_removes_runtime_logs(tmp_path) -> None:
    events_path = tmp_path / "events.jsonl"
    queue_path = tmp_path / "tasks.jsonl"
    usage_path = tmp_path / "usage.jsonl"
    agent_runs_path = tmp_path / "agent_runs.jsonl"
    control_path = tmp_path / "control.jsonl"
    events_path.write_text("event\n", encoding="utf-8")
    queue_path.write_text("task\n", encoding="utf-8")
    usage_path.write_text("usage\n", encoding="utf-8")
    agent_runs_path.write_text("run\n", encoding="utf-8")

    reset_demo_state(
        events_path=events_path,
        queue_path=queue_path,
        usage_path=usage_path,
        agent_runs_path=agent_runs_path,
    )

    assert not events_path.exists()
    assert not queue_path.exists()
    assert not usage_path.exists()
    assert not agent_runs_path.exists()


def test_demo_server_reset_endpoint_removes_runtime_logs(tmp_path, monkeypatch) -> None:
    _set_voice_env(monkeypatch)

    web_dir = tmp_path / "web"
    web_dir.mkdir()
    (web_dir / "index.html").write_text("<html>dashboard</html>", encoding="utf-8")
    events_path = tmp_path / "events.jsonl"
    queue_path = tmp_path / "tasks.jsonl"
    usage_path = tmp_path / "usage.jsonl"
    agent_runs_path = tmp_path / "agent_runs.jsonl"
    control_path = tmp_path / "control.jsonl"
    events_path.write_text("event\n", encoding="utf-8")
    queue_path.write_text("task\n", encoding="utf-8")
    usage_path.write_text("usage\n", encoding="utf-8")
    agent_runs_path.write_text("run\n", encoding="utf-8")

    server = create_demo_http_server(
        DemoServerConfig(
            host="127.0.0.1",
            port=0,
            room="line",
            identity="mac-test",
            web_dir=web_dir,
            events_path=events_path,
            queue_path=queue_path,
            usage_path=usage_path,
            agent_runs_path=agent_runs_path,
            control_path=control_path,
            pairing_state_path=tmp_path / "pairing.json",
        )
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base_url = f"http://127.0.0.1:{server.server_port}"
        auth_header = _pair_phone(base_url, tmp_path / "pairing.json")
        payload = _post_json(f"{base_url}/api/reset", headers=auth_header)

        assert payload == {"ok": True}
        assert not events_path.exists()
        assert not queue_path.exists()
        assert not usage_path.exists()
        assert not agent_runs_path.exists()
        control_events = EventLog(control_path).read_all()
        assert control_events[0].type == "control.reset_requested"
        assert control_events[0].payload["client"] == "127.0.0.1"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_demo_server_rejects_unpaired_token_and_reset_requests(tmp_path, monkeypatch) -> None:
    _set_voice_env(monkeypatch)

    web_dir = tmp_path / "web"
    web_dir.mkdir()
    (web_dir / "index.html").write_text("<html>dashboard</html>", encoding="utf-8")
    server = create_demo_http_server(
        DemoServerConfig(
            host="127.0.0.1",
            port=0,
            room="line",
            identity="mac-test",
            web_dir=web_dir,
            events_path=tmp_path / "events.jsonl",
            queue_path=tmp_path / "tasks.jsonl",
            usage_path=tmp_path / "usage.jsonl",
            agent_runs_path=tmp_path / "agent_runs.jsonl",
            pairing_state_path=tmp_path / "pairing.json",
        )
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base_url = f"http://127.0.0.1:{server.server_port}"

        try:
            _get_json(f"{base_url}/api/token")
        except HTTPError as error:
            assert error.code == 401
        else:
            raise AssertionError("Expected /api/token to require pairing auth")

        try:
            _post_json(f"{base_url}/api/reset")
        except HTTPError as error:
            assert error.code == 401
        else:
            raise AssertionError("Expected /api/reset to require pairing auth")

        auth_header = _pair_phone(base_url, tmp_path / "pairing.json")
        token_payload = _get_json(f"{base_url}/api/token", headers=auth_header)
        assert token_payload["token"]
    finally:
        server.shutdown()
        thread.join(timeout=5)


def _pair_phone(base_url: str, state_path: Path) -> dict[str, str]:
    session = PairingStore(state_path).start_pairing(server_url=base_url)
    payload = _post_json(
        f"{base_url}/api/pair",
        body={"code": session.code, "deviceName": "pytest iPhone"},
    )
    assert payload["ok"] is True
    assert payload["token"]
    assert payload["phoneId"]
    return {"Authorization": f"Bearer {payload['token']}"}


def _set_voice_env(monkeypatch) -> None:
    monkeypatch.setenv("LIVEKIT_URL", "wss://example.livekit.cloud")
    monkeypatch.setenv("LIVEKIT_API_KEY", TEST_LIVEKIT_KEY)
    monkeypatch.setenv("LIVEKIT_API_SECRET", TEST_LIVEKIT_HMAC)
    monkeypatch.setenv("DEEPGRAM_API_KEY", TEST_STT_KEY)
    monkeypatch.setenv("ELEVENLABS_API_KEY", TEST_TTS_KEY)
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", TEST_TTS_VOICE)
    monkeypatch.setenv("ELEVENLABS_MODEL", TEST_TTS_MODEL)


def _get_json(url: str, *, headers: dict[str, str] | None = None) -> dict:
    request = Request(url, headers=headers or {})
    with urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def _post_json(url: str, *, body: dict | None = None, headers: dict[str, str] | None = None) -> dict:
    data = b"" if body is None else json.dumps(body).encode("utf-8")
    request = Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    with urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))
