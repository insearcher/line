# Archive Notice

This repository is archived and is no longer under active development.

## Decision

On 2026-05-04, after evaluating
[Happy](https://github.com/slopus/happy), we decided not to continue developing
line as a separate product.

Happy already provides the core product direction we wanted to explore with
line: mobile and web control for coding agents, remote session management, and
a voice workflow built around an ElevenLabs agent that can send messages to
coding sessions and handle permission requests.

## What Remains Useful

The repository is kept as a historical implementation and research artifact.
Some parts may still be useful as references:

- LiveKit-based audio transport experiments.
- Marker-gated voice capture.
- Codex app-server voice backend integration.
- Local gateway and iOS pairing experiments.
- Claude Code channel bridge notes.

## Development Status

Do not start new feature work here by default. Future work should happen in or
around Happy unless there is a clearly separate reason to revisit this codebase.
