# Claude Code Channel Bridge

This bridge is an experimental path for talking to a running Claude Code session
from the local voice demo. The public v0.1 happy path is Codex app-server; use
this only for local experiments.

Official references:

- [Claude Code Channels](https://code.claude.com/docs/en/channels.md)
- [Claude Code Channels reference](https://code.claude.com/docs/en/channels-reference.md)
- [Claude Code remote control](https://code.claude.com/docs/en/remote-control.md)

## Requirements

- Claude Code `v2.1.80+`.
- `bun`.
- Claude Code authenticated through `claude.ai`. The research-preview channel
  feature does not work through plain API-key auth.

Custom channels are still a research-preview API. Launch this bridge only for
local testing and keep it bound to `127.0.0.1`.

Channels can also be disabled at the Claude organization level. If Claude Code
reports that Channels are not enabled for the organization, this bridge cannot be
used in that org. Use the Claude CLI backend in [advanced modes](advanced.md)
instead.

## Install

```bash
cd channels/claude-voice-channel
bun install
bun test
```

## Start Claude With The Channel

From the repository root:

```bash
printf 'VOICE_CHANNEL_TOKEN=%s\n' "$(openssl rand -hex 32)" > .env.claude-channel.local
set -a
. ./.env.claude-channel.local
set +a

claude \
  --mcp-config '{"mcpServers":{"line":{"command":"bun","args":["./channels/claude-voice-channel/server.ts"]}}}' \
  --dangerously-load-development-channels server:line
```

Keep this Claude Code session open. Channel events only reach Claude while the
session is running.

The channel server exposes:

- `POST http://127.0.0.1:8790/voice` for inbound voice text.
- `GET http://127.0.0.1:8790/events` for outbound SSE replies.
- `GET http://127.0.0.1:8790/health` for a local health check.

Manual text test:

```bash
uv run line claude-channel-send \
  "Скажи коротко, что канал работает" \
  --token "$VOICE_CHANNEL_TOKEN"
```

Claude should receive the message as a channel event. It is instructed to call
the MCP tool `reply_to_voice` for any user-facing answer.

## Run Voice Demo In Claude Mode

Terminal 1, keep Claude running with the command above.

Terminal 2:

```bash
set -a
. ./.env.claude-channel.local
set +a

uv run line lowlevel-worker \
  --room line-dev \
  --identity line-worker \
  --claude-channel-url http://127.0.0.1:8790 \
  --claude-channel-token "$VOICE_CHANNEL_TOKEN"
```

Terminal 3:

```bash
uv run line demo-server --room line-dev --identity mac-test
```

Open `http://127.0.0.1:8787`, connect, and speak. In Claude mode the worker:

1. Receives browser mic audio from LiveKit.
2. Gates audio locally with Silero VAD.
3. Sends speech chunks to Deepgram STT.
4. Posts the final transcript to Claude channel `/voice`.
5. Reads Claude's `reply_to_voice` tool calls from `/events`.
6. Speaks those replies through the existing TTS publisher.

## Permission Relay

The bridge advertises `experimental["claude/channel/permission"]`. If Claude
sends a permission request, the server emits an SSE `permission_request` event.
For a manual approval test, send either:

```bash
curl -X POST http://127.0.0.1:8790/permission \
  -H 'content-type: application/json' \
  -H "authorization: Bearer $VOICE_CHANNEL_TOKEN" \
  -d '{"request_id":"req_123","behavior":"allow"}'
```

or:

```bash
uv run line claude-channel-send "allow req_123" --token "$VOICE_CHANNEL_TOKEN"
```

Do not expose the bridge outside localhost without real authentication and an
allowlist. Incoming channel text is prompt input to a coding agent.
