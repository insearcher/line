from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from line.agent_backends import (
    AgentBackendError,
    AgentProcessResult,
    ClaudeCliBackend,
    ClaudeCliConfig,
    DEFAULT_VOICE_SYSTEM_PROMPT,
    build_claude_cli_argv,
)


def test_build_claude_cli_argv_uses_haiku_model_by_default() -> None:
    argv = build_claude_cli_argv(ClaudeCliConfig(), "Say briefly: ok")

    assert argv == [
        "claude",
        "--print",
        "--model",
        "haiku",
        "--output-format",
        "text",
        "--append-system-prompt",
        DEFAULT_VOICE_SYSTEM_PROMPT,
        "Say briefly: ok",
    ]


def test_build_claude_cli_argv_allows_custom_voice_prompt() -> None:
    argv = build_claude_cli_argv(
        ClaudeCliConfig(system_prompt="Reply with one word."),
        "status",
    )

    assert argv[-3:] == ["--append-system-prompt", "Reply with one word.", "status"]


def test_build_claude_cli_argv_includes_optional_controls(tmp_path: Path) -> None:
    argv = build_claude_cli_argv(
        ClaudeCliConfig(
            command="claude",
            model="haiku",
            permission_mode="acceptEdits",
            max_budget_usd=0.25,
        ),
        "check tests",
    )

    assert "--permission-mode" in argv
    assert "acceptEdits" in argv
    assert "--max-budget-usd" in argv
    assert "0.25" in argv
    assert argv[-1] == "check tests"


def test_claude_cli_backend_returns_trimmed_stdout(tmp_path: Path) -> None:
    calls: list[tuple[list[str], Path | None, float]] = []

    async def runner(argv: list[str], cwd: Path | None, timeout_seconds: float) -> AgentProcessResult:
        calls.append((argv, cwd, timeout_seconds))
        return AgentProcessResult(returncode=0, stdout="  Done.\n", stderr="")

    backend = ClaudeCliBackend(
        ClaudeCliConfig(cwd=tmp_path, timeout_seconds=12.5),
        process_runner=runner,
    )

    result = asyncio.run(backend.run("status"))

    assert result.reply == "Done."
    assert result.model == "haiku"
    assert calls[0][0][-1] == "status"
    assert calls[0][1] == tmp_path
    assert calls[0][2] == 12.5


def test_claude_cli_backend_raises_on_failed_process() -> None:
    async def runner(argv: list[str], cwd: Path | None, timeout_seconds: float) -> AgentProcessResult:
        del argv, cwd, timeout_seconds
        return AgentProcessResult(returncode=2, stdout="", stderr="model not found")

    backend = ClaudeCliBackend(ClaudeCliConfig(), process_runner=runner)

    with pytest.raises(AgentBackendError, match="model not found"):
        asyncio.run(backend.run("status"))
