# line gateway

This directory contains the Python package and CLI for the local line gateway.
It owns pairing, LiveKit token issuance, event logs, speech worker orchestration,
the local gateway HTTP API, and in-process agent adapters. The static browser
client lives in `../clients/web` and can be served by `line demo-server`.

This guide covers the public v0.1 happy path: local gateway, iOS app, LiveKit
Cloud, Deepgram STT, ElevenLabs TTS, and Codex app-server as the agent backend.

Run commands from this directory unless another directory is shown.

## 1. Install dependencies

```bash
uv sync --all-extras --dev
```

You also need the Codex CLI on `PATH` and authenticated before starting voice
workflows.

## 2. Configure environment

```bash
cp .env.example .env
```

Fill these values:

- `LIVEKIT_URL`
- `LIVEKIT_API_KEY`
- `LIVEKIT_API_SECRET`
- `DEEPGRAM_API_KEY`
- `DEEPGRAM_LANGUAGE`
- `TTS_PROVIDER=elevenlabs`
- `TTS_LANGUAGE`
- `ELEVENLABS_API_KEY`
- `ELEVENLABS_VOICE_ID`
- `ELEVENLABS_MODEL`

Do not commit `.env`.

Run the doctor check:

```bash
uv run line doctor --agent-backend codex-app-server --agent-cwd /path/to/workspace
```

## 3. Start the local gateway

The demo server command starts the local gateway HTTP API. It provides LiveKit
tokens, pairing, reset controls, event logs, and serves the development
dashboard from `../clients/web`.

For a physical iPhone, bind to all interfaces on a trusted LAN or private VPN:

```bash
uv run line demo-server --host 0.0.0.0 --room line-dev --identity mac-test
```

For simulator-only testing, `127.0.0.1` is enough:

```bash
uv run line demo-server --room line-dev --identity mac-test
```

The server prints a development dashboard token and a local dashboard URL with
that token in the fragment. The dashboard is a dev-only tool; JSON APIs require
either this dashboard token or a paired iOS device token.

## 4. Start the voice worker

```bash
uv run line lowlevel-worker \
  --room line-dev \
  --identity line-worker \
  --agent-backend codex-app-server \
  --agent-cwd /path/to/workspace \
  --capture-mode markers \
  --capture-start "start command" \
  --capture-submit "send command" \
  --capture-cancel "cancel"
```

The worker:

1. Joins the LiveKit room.
2. Receives phone audio.
3. Runs local Silero VAD before sending speech chunks to Deepgram.
4. Buffers text between the start and submit markers.
5. Sends the captured command to Codex app-server.
6. Speaks Codex `reply_to_voice` updates and the final agent reply through ElevenLabs.

## 5. Pair the phone

With the server running, create a one-time gateway invitation:

```bash
uv run line pair --server-url http://YOUR-MAC-LAN-IP:8787
```

Scan the printed QR code in the iOS app, or open the printed `line://pair` deep
link on the phone. The app stores the returned phone token in Keychain and uses
it for privileged gateway APIs such as `/api/token` and `/api/reset`.

Manual URL and pairing-code entry remain available in the app's Advanced section
for development and simulator workflows.

## Manual text check

Before testing audio, verify the Codex backend with text:

```bash
uv run line agent-run \
  "Reply with one short sentence: the Codex backend works" \
  --agent-backend codex-app-server \
  --agent-model gpt-5.5 \
  --agent-cwd /path/to/workspace
```

## Runtime state

line writes local runtime state under ignored paths inside this directory:

- `.env`
- `data/events.jsonl`
- `data/usage.jsonl`
- `data/agent_runs.jsonl`
- `data/control.jsonl`
- `data/pairing_state.json`
- `logs/`

These files may contain transcripts, local URLs, pairing state, and operational
details. Do not commit them. These paths are ignored by git except for
`.env.example`.

## Tests

```bash
uv run pytest -q
```

## Troubleshooting

Run:

```bash
uv run line doctor --agent-backend codex-app-server --agent-cwd /path/to/workspace
```

Common failures:

- `FAIL voice env`: `.env` is missing required LiveKit, Deepgram, or TTS values.
- `FAIL codex command`: install or authenticate the Codex CLI.
- Deepgram 401 errors: the `DEEPGRAM_API_KEY` is missing, expired, or from the
  wrong project.
- No phone connection: confirm the iPhone can reach `http://YOUR-MAC-LAN-IP:8787`
  on the same LAN or private VPN.
