# Security Policy

line is currently a developer-first voice bridge. Treat it as a local tool that
can hand spoken instructions to a coding agent with broad access to the selected
workspace.

## Supported versions

Security fixes are considered for the current `main` branch until versioned
releases exist.

## Reporting a vulnerability

Please do not file public issues for vulnerabilities. Use GitHub private
vulnerability reporting if it is enabled for the repository, or contact the
maintainer privately through the profile attached to the repository.

## Operational safety

- Run the Codex app-server backend only in workspaces or VMs that can be reset.
- Keep `.env`, LiveKit credentials, Deepgram keys, ElevenLabs keys, pairing
  state, dashboard tokens, room tokens, and runtime logs out of git.
- Bind the gateway demo server to `127.0.0.1` by default. Use `--host 0.0.0.0` only on a
  trusted LAN or private VPN.
- Pair only devices you control. Gateway invitations are one-time credentials for
  the local gateway; dashboard tokens are development-only credentials.
- Review the selected Codex sandbox and approval policy before using line on a
  real project. The current public happy path uses full local agent access.
