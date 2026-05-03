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
