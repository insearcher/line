# Agent Backend Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the gateway agent backend implementation into focused Python modules while keeping the existing CLI, worker behavior, tests, and public import path stable.

**Architecture:** Codex should remain an in-process gateway agent backend, not a top-level `bridges/` package. Top-level `bridges/` is reserved for external sidecar bridge processes like `bridges/cc-channel/`, where the worker talks to a separate runtime over HTTP/SSE. The Codex app-server integration is owned by the Python worker lifecycle and should live under `gateway/src/line/agent_backends/`, with `gateway/src/line/agent_backend.py` kept as a compatibility facade.

**Tech Stack:** Python 3.12, uv, pytest, existing Codex app-server JSON-RPC over stdio/WebSocket, existing Claude CLI subprocess integration.

---

## Design Decisions

1. Do not create `bridges/codex/` in this change.
   - `bridges/cc-channel/` is a Bun/MCP sidecar loaded by Claude Code.
   - Codex is already accessed through `codex app-server`; Line only needs a Python client/backend.
   - Adding another bridge process would duplicate lifecycle, transport, auth, timeout, and failure handling.

2. Add a new internal package:
   - `gateway/src/line/agent_backends/__init__.py`
   - `gateway/src/line/agent_backends/base.py`
   - `gateway/src/line/agent_backends/claude_cli.py`
   - `gateway/src/line/agent_backends/codex_app_server.py`

3. Keep the old public import module:
   - `gateway/src/line/agent_backend.py` becomes a thin re-export facade.
   - Existing imports from `line.agent_backend` must keep working.
   - No deprecation warning in this PR; warnings would add CLI/test noise.

4. Keep external contracts unchanged:
   - CLI backend names: `router`, `claude-cli`, `codex-app-server`.
   - `line doctor` default backend: `codex-app-server`.
   - Codex backend label: `codex`.
   - Claude default model: `haiku`.
   - Codex model normalization: `--agent-model haiku` means Codex default, not literal `haiku`.
   - Worker dispatch order: `cc_channel_client`, then `agent_backend`, then router queue.
   - Events: `agent_backend.dispatched`, `agent_backend.running`, `agent_backend.done`, `agent_backend.failed`.
   - Dynamic tool name: `reply_to_voice`.

5. Treat remote Codex as a transport/deployment mode, not a bridge package.
   - `--codex-endpoint ws://...` means the gateway connects to an existing Codex app-server.
   - For a VM or another computer, prefer SSH tunnel/VPN/trusted private network.
   - `--agent-cwd` in remote mode is a path in the Codex app-server environment.
   - A separate Codex bridge is only justified later if Line needs its own authenticated remote workspace service.

## File Map

Create:

- `gateway/src/line/agent_backends/__init__.py`
  - Public package exports for the new module path.

- `gateway/src/line/agent_backends/base.py`
  - Shared exceptions, result dataclasses, voice prompt/tool constants, and optional typing protocol.

- `gateway/src/line/agent_backends/claude_cli.py`
  - Claude CLI config, argv builder, backend class, subprocess runner, subprocess result type.

- `gateway/src/line/agent_backends/codex_app_server.py`
  - Codex app-server config, backend class, JSON-RPC client, stdio/WebSocket transports, Codex parameter builders, voice reply dynamic tool handling.

- `gateway/tests/test_claude_agent_backend.py`
  - Claude-specific tests moved from `test_agent_backend.py`.

- `gateway/tests/test_codex_app_server_backend.py`
  - Codex-specific tests moved from `test_agent_backend.py`.

Modify:

- `gateway/src/line/agent_backend.py`
  - Replace implementation with compatibility re-exports.

- `gateway/src/line/cli.py`
  - Import backend symbols from `line.agent_backends`, or keep facade imports if minimizing churn. Preferred: new package imports for production code.

- `gateway/src/line/lowlevel_worker.py`
  - Import backend symbols from `line.agent_backends`.

- `gateway/tests/test_agent_backend.py`
  - Reduce to facade compatibility tests.

- `README.md`
  - Clarify that `bridges/cc-channel/` is an external bridge and Codex is the gateway agent backend.

- `docs/advanced.md`
  - Add one short note under external Codex/CC sections to make the boundary explicit.

Do not modify:

- `bridges/cc-channel/*` unless a test reveals accidental doc mismatch.
- CLI argument names or command examples.
- Agent run schema.
- Dashboard API.

## Task 1: Add Compatibility Coverage First

**Files:**
- Modify: `gateway/tests/test_agent_backend.py`

- [ ] **Step 1: Replace the monolithic test file with facade tests after moving behavior tests in later tasks**

Use this as the final shape of `gateway/tests/test_agent_backend.py`:

```python
from __future__ import annotations

from line import agent_backend
from line.agent_backends import (
    AgentBackendError,
    AgentJobResult,
    AgentProcessResult,
    ClaudeCliBackend,
    ClaudeCliConfig,
    CodexAppServerBackend,
    CodexAppServerConfig,
    VoiceReply,
)


def test_agent_backend_facade_reexports_public_symbols() -> None:
    assert agent_backend.AgentBackendError is AgentBackendError
    assert agent_backend.AgentJobResult is AgentJobResult
    assert agent_backend.AgentProcessResult is AgentProcessResult
    assert agent_backend.VoiceReply is VoiceReply
    assert agent_backend.ClaudeCliConfig is ClaudeCliConfig
    assert agent_backend.ClaudeCliBackend is ClaudeCliBackend
    assert agent_backend.CodexAppServerConfig is CodexAppServerConfig
    assert agent_backend.CodexAppServerBackend is CodexAppServerBackend


def test_agent_backend_facade_keeps_basic_constructors() -> None:
    claude = agent_backend.ClaudeCliBackend(agent_backend.ClaudeCliConfig())
    codex = agent_backend.CodexAppServerBackend(agent_backend.CodexAppServerConfig())

    assert claude.label == "haiku"
    assert codex.label == "codex"
```

- [ ] **Step 2: Do not run this test alone yet**

Expected: it will fail until the new package and facade are created.

## Task 2: Create Shared Backend Module

**Files:**
- Create: `gateway/src/line/agent_backends/base.py`
- Create: `gateway/src/line/agent_backends/__init__.py`

- [ ] **Step 1: Move shared symbols into `base.py`**

Move these unchanged from `gateway/src/line/agent_backend.py`:

```python
AgentBackendError
DEFAULT_VOICE_SYSTEM_PROMPT
VOICE_REPLY_TOOL_NAME
VOICE_REPLY_STATUSES
VoiceReply
AgentJobResult
```

Add this optional protocol to make worker typing explicit without changing behavior:

```python
from typing import Protocol


class AgentBackend(Protocol):
    @property
    def label(self) -> str: ...

    @property
    def model(self) -> str: ...

    async def run(self, prompt: str) -> AgentJobResult: ...
```

- [ ] **Step 2: Export shared symbols from package `__init__.py`**

Initial content:

```python
from line.agent_backends.base import (
    AgentBackend,
    AgentBackendError,
    AgentJobResult,
    DEFAULT_VOICE_SYSTEM_PROMPT,
    VOICE_REPLY_STATUSES,
    VOICE_REPLY_TOOL_NAME,
    VoiceReply,
)

__all__ = [
    "AgentBackend",
    "AgentBackendError",
    "AgentJobResult",
    "DEFAULT_VOICE_SYSTEM_PROMPT",
    "VOICE_REPLY_STATUSES",
    "VOICE_REPLY_TOOL_NAME",
    "VoiceReply",
]
```

## Task 3: Move Claude CLI Backend

**Files:**
- Create: `gateway/src/line/agent_backends/claude_cli.py`
- Modify: `gateway/src/line/agent_backends/__init__.py`
- Create: `gateway/tests/test_claude_agent_backend.py`

- [ ] **Step 1: Move Claude-specific symbols**

Move these unchanged into `claude_cli.py`:

```python
AgentProcessResult
ProcessRunner
ClaudeCliConfig
ClaudeCliBackend
build_claude_cli_argv
run_process
```

Import shared symbols from `line.agent_backends.base`:

```python
from line.agent_backends.base import (
    AgentBackendError,
    AgentJobResult,
    DEFAULT_VOICE_SYSTEM_PROMPT,
)
```

- [ ] **Step 2: Export Claude symbols from package `__init__.py`**

Add imports and `__all__` entries:

```python
from line.agent_backends.claude_cli import (
    AgentProcessResult,
    ClaudeCliBackend,
    ClaudeCliConfig,
    ProcessRunner,
    build_claude_cli_argv,
    run_process,
)
```

- [ ] **Step 3: Move Claude tests**

Move these tests from the old `gateway/tests/test_agent_backend.py` into `gateway/tests/test_claude_agent_backend.py` and update imports to `line.agent_backends.claude_cli` plus `line.agent_backends.base`:

```python
test_build_claude_cli_argv_uses_haiku_model_by_default
test_build_claude_cli_argv_allows_custom_voice_prompt
test_build_claude_cli_argv_includes_optional_controls
test_claude_cli_backend_returns_trimmed_stdout
test_claude_cli_backend_raises_on_failed_process
```

- [ ] **Step 4: Run Claude tests**

Run:

```bash
cd gateway
uv run pytest tests/test_claude_agent_backend.py -q
```

Expected: tests pass after Task 6 facade cleanup; if run before facade cleanup, failures should be import-only and localized.

## Task 4: Move Codex App-Server Backend

**Files:**
- Create: `gateway/src/line/agent_backends/codex_app_server.py`
- Modify: `gateway/src/line/agent_backends/__init__.py`
- Create: `gateway/tests/test_codex_app_server_backend.py`

- [ ] **Step 1: Move Codex-specific symbols**

Move these unchanged into `codex_app_server.py`:

```python
CodexTurnResult
CodexAppServerConfig
CodexJsonRpcTransport
CodexTransportFactory
CodexAppServerBackend
build_codex_app_server_argv
build_codex_thread_start_params
build_codex_thread_resume_params
build_codex_turn_start_params
build_voice_reply_dynamic_tool
select_codex_spoken_reply
_sandbox_policy
start_codex_transport
CodexAppServerProcessTransport
CodexAppServerWebSocketTransport
CodexAppServerClient
_read_http_headers
_validate_websocket_handshake
_websocket_accept
_dynamic_tool_response
_response_result
_extract_thread_id
_extract_turn_id
_format_rpc_error
```

Import shared symbols from `line.agent_backends.base`:

```python
from line.agent_backends.base import (
    AgentBackendError,
    AgentJobResult,
    DEFAULT_VOICE_SYSTEM_PROMPT,
    VOICE_REPLY_STATUSES,
    VOICE_REPLY_TOOL_NAME,
    VoiceReply,
)
```

- [ ] **Step 2: Export Codex symbols from package `__init__.py`**

Add imports and `__all__` entries:

```python
from line.agent_backends.codex_app_server import (
    CodexAppServerBackend,
    CodexAppServerConfig,
    CodexJsonRpcTransport,
    CodexTransportFactory,
    CodexTurnResult,
    build_codex_app_server_argv,
    build_codex_thread_resume_params,
    build_codex_thread_start_params,
    build_codex_turn_start_params,
    build_voice_reply_dynamic_tool,
    select_codex_spoken_reply,
    start_codex_transport,
)
```

- [ ] **Step 3: Move Codex tests**

Move the Codex tests and helper fakes from old `gateway/tests/test_agent_backend.py` into `gateway/tests/test_codex_app_server_backend.py`.

Update imports to:

```python
from line.agent_backends.base import VoiceReply
from line.agent_backends.codex_app_server import (
    CodexAppServerBackend,
    CodexAppServerConfig,
    build_codex_app_server_argv,
    build_codex_thread_resume_params,
    build_codex_thread_start_params,
    build_codex_turn_start_params,
)
```

- [ ] **Step 4: Run Codex tests**

Run:

```bash
cd gateway
uv run pytest tests/test_codex_app_server_backend.py -q
```

Expected: tests pass. Pay special attention to timeout cleanup and WebSocket tests.

## Task 5: Replace `line.agent_backend` With Facade

**Files:**
- Modify: `gateway/src/line/agent_backend.py`
- Modify: `gateway/tests/test_agent_backend.py`

- [ ] **Step 1: Replace implementation with explicit re-exports**

Use this content shape:

```python
from __future__ import annotations

from line.agent_backends import (
    AgentBackend,
    AgentBackendError,
    AgentJobResult,
    AgentProcessResult,
    ClaudeCliBackend,
    ClaudeCliConfig,
    CodexAppServerBackend,
    CodexAppServerConfig,
    CodexJsonRpcTransport,
    CodexTransportFactory,
    CodexTurnResult,
    DEFAULT_VOICE_SYSTEM_PROMPT,
    ProcessRunner,
    VOICE_REPLY_STATUSES,
    VOICE_REPLY_TOOL_NAME,
    VoiceReply,
    build_claude_cli_argv,
    build_codex_app_server_argv,
    build_codex_thread_resume_params,
    build_codex_thread_start_params,
    build_codex_turn_start_params,
    build_voice_reply_dynamic_tool,
    run_process,
    select_codex_spoken_reply,
    start_codex_transport,
)

__all__ = [
    "AgentBackend",
    "AgentBackendError",
    "AgentJobResult",
    "AgentProcessResult",
    "ClaudeCliBackend",
    "ClaudeCliConfig",
    "CodexAppServerBackend",
    "CodexAppServerConfig",
    "CodexJsonRpcTransport",
    "CodexTransportFactory",
    "CodexTurnResult",
    "DEFAULT_VOICE_SYSTEM_PROMPT",
    "ProcessRunner",
    "VOICE_REPLY_STATUSES",
    "VOICE_REPLY_TOOL_NAME",
    "VoiceReply",
    "build_claude_cli_argv",
    "build_codex_app_server_argv",
    "build_codex_thread_resume_params",
    "build_codex_thread_start_params",
    "build_codex_turn_start_params",
    "build_voice_reply_dynamic_tool",
    "run_process",
    "select_codex_spoken_reply",
    "start_codex_transport",
]
```

- [ ] **Step 2: Run facade tests**

Run:

```bash
cd gateway
uv run pytest tests/test_agent_backend.py -q
```

Expected: facade tests pass and prove identity equality with the new package.

## Task 6: Update Production Imports

**Files:**
- Modify: `gateway/src/line/cli.py`
- Modify: `gateway/src/line/lowlevel_worker.py`
- Modify: `gateway/tests/test_cli.py`
- Modify: `gateway/tests/test_lowlevel_worker.py`

- [ ] **Step 1: Change production imports to the new package**

In `gateway/src/line/cli.py`, replace:

```python
from line.agent_backend import (...)
```

with:

```python
from line.agent_backends import (
    AgentBackendError,
    AgentJobResult,
    ClaudeCliBackend,
    ClaudeCliConfig,
    CodexAppServerBackend,
    CodexAppServerConfig,
)
```

In `gateway/src/line/lowlevel_worker.py`, replace the backend import with:

```python
from line.agent_backends import (
    AgentBackendError,
    AgentJobResult,
    ClaudeCliBackend,
    ClaudeCliConfig,
    CodexAppServerBackend,
    CodexAppServerConfig,
)
```

- [ ] **Step 2: Change tests to new imports where they are not testing compatibility**

In `gateway/tests/test_cli.py` and `gateway/tests/test_lowlevel_worker.py`, import `AgentJobResult` and `VoiceReply` from `line.agent_backends`.

- [ ] **Step 3: Keep `build_agent_backend` in `lowlevel_worker.py` for now**

Do not move `build_agent_backend` to a new factory module in this PR. It currently consumes `LowLevelWorkerConfig`; moving it now would introduce a new config mapping layer without reducing risk.

- [ ] **Step 4: Run CLI and worker tests**

Run:

```bash
cd gateway
uv run pytest tests/test_cli.py tests/test_lowlevel_worker.py -q
```

Expected: all tests pass.

## Task 7: Documentation Boundary Note

**Files:**
- Modify: `README.md`
- Modify: `docs/advanced.md`

- [ ] **Step 1: Clarify repository layout**

In `README.md`, keep the existing layout and add one sentence after it:

```markdown
Codex app-server support lives inside the Python gateway as an agent backend; `bridges/` is for external sidecar adapters such as the Claude Code channel bridge.
```

- [ ] **Step 2: Clarify advanced modes**

In `docs/advanced.md`, add one sentence near "External Codex endpoint":

```markdown
This is still a gateway agent backend: the worker either starts Codex app-server itself or connects to an already running Codex app-server endpoint.
```

Near "CC channel bridge", add:

```markdown
Unlike Codex app-server, this is a separate bridge process hosted by Claude Code through MCP and reached by the gateway over local HTTP/SSE.
```

- [ ] **Step 3: Run docs grep**

Run:

```bash
rg -n "bridges/codex|line.agent_backend|agent_backends|codex-app-server|cc-channel" README.md docs gateway/src gateway/tests
```

Expected:
- No `bridges/codex` references outside negative guidance in this plan.
- `line.agent_backend` references only in compatibility tests or facade comments if any.
- Commands still show `codex-app-server`.

## Task 8: Full Verification

**Files:**
- No edits.

- [ ] **Step 1: Run all gateway tests**

Run:

```bash
cd gateway
uv run pytest -q
```

Expected: all tests pass.

- [ ] **Step 2: Run import smoke check**

Run:

```bash
cd gateway
uv run python -c "from line.agent_backend import CodexAppServerBackend; from line.agent_backends import ClaudeCliBackend; print(CodexAppServerBackend.__name__, ClaudeCliBackend.__name__)"
```

Expected:

```text
CodexAppServerBackend ClaudeCliBackend
```

- [ ] **Step 3: Run parser smoke check**

Run:

```bash
cd gateway
uv run line agent-run "noop" --agent-backend router
```

Expected:
- Exit code `2`.
- Error includes `agent-run requires --agent-backend claude-cli or codex-app-server`.

- [ ] **Step 4: Optional live Codex check**

Only run this if Codex CLI is installed and authenticated:

```bash
cd gateway
uv run line agent-run \
  "Reply with one short sentence: backend split smoke test" \
  --agent-backend codex-app-server \
  --agent-cwd /path/to/workspace
```

Expected: one short spoken-friendly reply from Codex. If this fails because Codex CLI is unavailable or unauthenticated, record it as an environment limitation, not a refactor failure.

## Known Pitfalls

- Do not put Codex under `bridges/`; that would add an unnecessary sidecar boundary.
- Preserve `AgentBackendError` identity. CLI and worker catch this exact class.
- Do not duplicate `DEFAULT_VOICE_SYSTEM_PROMPT`; Claude and Codex configs share it.
- Do not change Codex `sandbox` vs `sandboxPolicy` keys. Thread params and turn params intentionally differ.
- Do not change `reply_to_voice` status selection. Voice UX depends on preferring final dynamic tool replies.
- Do not change `cc_channel_client` precedence. When `--cc-channel-url` is set, the worker bypasses agent backends.
- Do not move `build_agent_backend` into the new package until there is a backend config object independent of `LowLevelWorkerConfig`.
- Keep `aclose()` calls on `agent-run`, worker shutdown, and Codex timeout.

## Self-Review

Spec coverage:

- Codex/CC boundary is explicit.
- New Python module ownership is explicit.
- Compatibility import path is preserved.
- CLI, worker, event, and docs contracts are listed.
- Verification covers focused tests, full tests, imports, parser behavior, and optional live Codex.

Placeholder scan:

- No placeholder markers or unspecified follow-up tasks.
- Optional live check has explicit skip condition and expected interpretation.

Type consistency:

- New package path is consistently `line.agent_backends`.
- Facade path remains `line.agent_backend`.
- Backend names remain `claude-cli` and `codex-app-server`.
