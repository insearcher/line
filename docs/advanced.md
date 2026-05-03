# Advanced and Experimental Modes

The public v0.1 happy path is Codex app-server. The repository also contains
older MVP paths that are useful for development but should be treated as
experimental.

Run gateway commands from `gateway/`.

## Router mode

Router mode keeps real agents out of the voice loop and writes fake tasks to a
local JSONL queue.

```bash
cd gateway
uv run line dry-run "Ask Codex to check the LiveKit worker"
uv run line dry-run "status"
uv run line dry-run "cancel"
```

The queue is written to `data/line_tasks.jsonl`.

## Browser dashboard

The gateway HTTP API server can serve the static web client from `clients/web`
at:

```text
http://127.0.0.1:8787
```

It is useful for inspecting events, usage counters, queued router tasks, and
agent run state during development.

## External Codex endpoint

This is still a gateway agent backend: the worker either starts Codex app-server
itself or connects to an already running Codex app-server endpoint.

You can start Codex app-server yourself and point line at it:

```bash
codex app-server --listen ws://127.0.0.1:4500
```

```bash
uv run line lowlevel-worker \
  --room line-dev \
  --identity line-worker \
  --agent-backend codex-app-server \
  --agent-cwd /path/to/workspace \
  --codex-endpoint ws://127.0.0.1:4500 \
  --codex-thread-id THREAD_ID_HERE \
  --capture-mode markers
```

Without `--codex-thread-id`, line creates a new thread on the endpoint.

For a VM or another computer, prefer an SSH tunnel or trusted private network
instead of exposing Codex app-server directly. In this mode `--agent-cwd` is a
path in the Codex app-server environment, not necessarily a path on the Mac
running the gateway.

## Claude CLI mode

Claude CLI mode is a fallback backend for local experiments:

```bash
uv run line agent-run \
  "Reply with one short sentence: the channel works" \
  --agent-backend claude-cli \
  --agent-model haiku \
  --agent-cwd /path/to/workspace
```

```bash
uv run line lowlevel-worker \
  --room line-dev \
  --identity line-worker \
  --agent-backend claude-cli \
  --agent-model haiku \
  --agent-cwd /path/to/workspace \
  --capture-mode markers
```

Set `--agent-permission-mode` explicitly if you want unattended edits.

## CC channel bridge

Unlike Codex app-server, this is a separate bridge process hosted by Claude Code
through MCP and reached by the gateway over local HTTP/SSE.

The Claude Code Channels bridge is documented separately in
[docs/cc-channel.md](cc-channel.md). It requires channel support in the Claude
organization and is not part of the main release path.
