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
- Pair only devices you control. Gateway invitations are one-time credentials for
  the local gateway; dashboard tokens are development-only credentials.
- Review the selected Codex sandbox and approval policy before using line on a
  real project.

## Trust boundaries

- The iOS app is trusted after completing a one-time gateway invitation.
- The browser dashboard is a development-only UI and uses a separate per-process
  dashboard token.
- The local gateway is trusted and should run on localhost, a trusted LAN, or a
  private VPN.
- LiveKit, Deepgram, and ElevenLabs receive the audio/text required by the
  configured workflow.
- Codex receives the captured command and can operate in the selected workspace.

## Agent permissions

The public happy path uses Codex app-server with full local agent access:

- `approvalPolicy=never`
- `sandbox=danger-full-access`
- `sandboxPolicy={type: dangerFullAccess}`

Use disposable repositories, VMs, or workspaces you can reset until stricter
policies are productized.

## Network exposure

`demo-server` defaults to `127.0.0.1`. Use `--host 0.0.0.0` only when the phone
must reach the Mac and the network is a trusted LAN or private VPN.

The gateway requires bearer auth for runtime JSON APIs that expose tokens,
transcripts, prompts, usage, agent runs, queued tasks, or reset controls.
`POST /api/pair` remains reachable so a one-time invitation can create a trusted
iOS device token.

## Speech capture

The iOS app continuously listens locally, but the worker sends commands to the
agent only after marker capture. With the default configuration, the sent command
is the text between `start command` and `send command`.
