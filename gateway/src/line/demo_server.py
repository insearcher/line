from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from line.agent_runs import AgentRunStore
from line.events import EventLog
from line.pairing import PairingError, PairingStore
from line.settings import VoiceConfig, load_env_file
from line.task_queue import TaskQueue
from line.tokens import generate_join_token
from line.usage import UsageLog


@dataclass(frozen=True)
class DemoServerConfig:
    host: str
    port: int
    room: str
    identity: str
    web_dir: Path
    events_path: Path
    queue_path: Path
    usage_path: Path
    agent_runs_path: Path = Path("data/agent_runs.jsonl")
    control_path: Path = Path("data/control.jsonl")
    pairing_state_path: Path = Path("data/pairing_state.json")
    env_path: Path = Path(".env")


def create_demo_http_server(config: DemoServerConfig) -> ThreadingHTTPServer:
    class DemoRequestHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, directory=str(config.web_dir), **kwargs)

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/api/token":
                if not self._is_authorized():
                    self._send_json({"ok": False, "error": "unauthorized"}, status=401)
                    return
                query = parse_qs(parsed.query)
                room = query.get("room", [config.room])[0]
                identity = query.get("identity", [config.identity])[0]
                EventLog(config.events_path).append(
                    "demo.token_requested",
                    {
                        "client": self.client_address[0],
                        "identity": identity,
                        "room": room,
                    },
                )
                self._send_json(_token_payload(config, room=room, identity=identity))
                return
            if parsed.path == "/api/events":
                query = parse_qs(parsed.query)
                after = query.get("after", [None])[0]
                event_log = EventLog(config.events_path)
                events = event_log.read_after(after) if after else event_log.read_all()
                self._send_json({"events": [asdict(event) for event in events]})
                return
            if parsed.path == "/api/tasks":
                tasks = TaskQueue(config.queue_path).list_tasks()
                self._send_json({"tasks": [asdict(task) for task in tasks]})
                return
            if parsed.path == "/api/usage":
                query = parse_qs(parsed.query)
                month = query.get("month", [""])[0]
                self._send_json({"summary": UsageLog(config.usage_path).monthly_summary(month)})
                return
            if parsed.path == "/api/agent-runs":
                runs = AgentRunStore(config.agent_runs_path).list_runs_newest_first()
                self._send_json({"agent_runs": [asdict(run) for run in runs]})
                return
            if parsed.path == "/":
                self.path = "/index.html"
            super().do_GET()

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/api/pair":
                try:
                    body = self._read_json_body()
                    credential = PairingStore(config.pairing_state_path).complete_pairing(
                        code=str(body.get("code", "")),
                        device_name=str(body.get("deviceName", "iPhone")),
                    )
                except (json.JSONDecodeError, PairingError) as error:
                    self._send_json({"ok": False, "error": str(error)}, status=400)
                    return
                self._send_json(
                    {
                        "ok": True,
                        "phoneId": credential.phone_id,
                        "token": credential.token,
                        "macDeviceId": credential.mac_device_id,
                    }
                )
                return
            if parsed.path == "/api/reset":
                if not self._is_authorized():
                    self._send_json({"ok": False, "error": "unauthorized"}, status=401)
                    return
                reset_demo_state(
                    events_path=config.events_path,
                    queue_path=config.queue_path,
                    usage_path=config.usage_path,
                    agent_runs_path=config.agent_runs_path,
                )
                EventLog(config.control_path).append(
                    "control.reset_requested",
                    {
                        "client": self.client_address[0],
                        "source": "demo-server",
                    },
                )
                self._send_json({"ok": True})
                return
            self.send_error(404)

        def log_message(self, format: str, *args) -> None:
            return

        def _read_json_body(self) -> dict:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0:
                return {}
            return json.loads(self.rfile.read(length).decode("utf-8"))

        def _is_authorized(self) -> bool:
            authorization = self.headers.get("Authorization", "")
            prefix = "Bearer "
            if authorization.startswith(prefix):
                return PairingStore(config.pairing_state_path).authenticate(authorization[len(prefix) :])
            header_token = self.headers.get("X-Line-Token")
            return PairingStore(config.pairing_state_path).authenticate(header_token)

        def _send_json(self, payload: dict, *, status: int = 200) -> None:
            body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

    return ThreadingHTTPServer((config.host, config.port), DemoRequestHandler)


def reset_demo_state(*, events_path: Path, queue_path: Path, usage_path: Path, agent_runs_path: Path) -> None:
    for path in (events_path, queue_path, usage_path, agent_runs_path):
        path.unlink(missing_ok=True)


def run_demo_server(config: DemoServerConfig) -> None:
    server = create_demo_http_server(config)
    url = f"http://{config.host}:{server.server_port}"
    print(f"line demo listening on {url}", flush=True)
    server.serve_forever()


def _token_payload(config: DemoServerConfig, *, room: str | None = None, identity: str | None = None) -> dict[str, str]:
    load_env_file(config.env_path)
    voice_config = VoiceConfig.from_env()
    resolved_room = room or config.room
    resolved_identity = identity or config.identity
    return {
        "url": voice_config.livekit_url,
        "room": resolved_room,
        "identity": resolved_identity,
        "token": generate_join_token(config=voice_config, room=resolved_room, identity=resolved_identity),
    }
