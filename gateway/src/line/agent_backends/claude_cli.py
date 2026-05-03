from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from line.agent_backends.base import AgentBackendError, AgentJobResult, DEFAULT_VOICE_SYSTEM_PROMPT


@dataclass(frozen=True)
class AgentProcessResult:
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class ClaudeCliConfig:
    command: str = "claude"
    model: str = "haiku"
    cwd: Path | None = None
    permission_mode: str | None = None
    timeout_seconds: float = 900.0
    max_budget_usd: float | None = None
    system_prompt: str | None = DEFAULT_VOICE_SYSTEM_PROMPT


ProcessRunner = Callable[[list[str], Path | None, float], Awaitable[AgentProcessResult]]


class ClaudeCliBackend:
    def __init__(
        self,
        config: ClaudeCliConfig,
        process_runner: ProcessRunner | None = None,
    ) -> None:
        self.config = config
        self._process_runner = process_runner or run_process

    @property
    def label(self) -> str:
        return self.config.model

    @property
    def model(self) -> str:
        return self.config.model

    async def run(self, prompt: str) -> AgentJobResult:
        argv = build_claude_cli_argv(self.config, prompt)
        result = await self._process_runner(argv, self.config.cwd, self.config.timeout_seconds)
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
            raise AgentBackendError(f"Claude CLI failed: {detail}")

        reply = result.stdout.strip()
        if not reply:
            raise AgentBackendError("Claude CLI returned an empty response")
        return AgentJobResult(
            prompt=prompt,
            reply=reply,
            model=self.config.model,
            stdout=result.stdout,
            stderr=result.stderr,
        )


def build_claude_cli_argv(config: ClaudeCliConfig, prompt: str) -> list[str]:
    argv = [
        config.command,
        "--print",
        "--model",
        config.model,
        "--output-format",
        "text",
    ]
    if config.permission_mode:
        argv.extend(["--permission-mode", config.permission_mode])
    if config.max_budget_usd is not None:
        argv.extend(["--max-budget-usd", f"{config.max_budget_usd:g}"])
    if config.system_prompt:
        argv.extend(["--append-system-prompt", config.system_prompt])
    argv.append(prompt)
    return argv


async def run_process(argv: list[str], cwd: Path | None, timeout_seconds: float) -> AgentProcessResult:
    process = await asyncio.create_subprocess_exec(
        *argv,
        cwd=str(cwd) if cwd is not None else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(process.communicate(), timeout_seconds)
    except TimeoutError as error:
        process.kill()
        await process.communicate()
        raise AgentBackendError(f"Claude CLI timed out after {timeout_seconds:g}s") from error
    return AgentProcessResult(
        returncode=process.returncode or 0,
        stdout=stdout_bytes.decode("utf-8", errors="replace"),
        stderr=stderr_bytes.decode("utf-8", errors="replace"),
    )
