# line gateway

This directory contains the Python package and CLI for the local line gateway.
It owns pairing, LiveKit token issuance, event logs, speech worker orchestration,
the local gateway HTTP API, and in-process agent adapters. The static browser
client lives in `../clients/web` and can be served by `line demo-server`.

## Setup

```bash
uv sync --all-extras --dev
cp .env.example .env
uv run pytest -q
```

Fill `.env` with LiveKit, Deepgram, and TTS credentials before running voice
workflows.

## Runtime state

Commands are intended to run from this directory. Relative defaults therefore
resolve under `gateway/`:

- `.env`
- `data/*.jsonl`
- `logs/`

These paths are ignored by git except for `.env.example`.
