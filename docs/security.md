# Security Model

line is not hardened for hostile networks. The current release is a
developer-controlled local workflow for trusted devices.

## Trust boundaries

- The iOS app is trusted after local pairing.
- The macOS demo server is trusted and should run on localhost, a trusted LAN, or
  a private VPN.
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

## Secrets

Never commit:

- `.env`
- LiveKit credentials
- Deepgram or ElevenLabs keys
- pairing state
- room tokens
- runtime logs under `data/` or `logs/`

## Network exposure

`demo-server` defaults to `127.0.0.1`. Use `--host 0.0.0.0` only when the phone
must reach the Mac and the network is trusted.

## Speech capture

The iOS app continuously listens locally, but the worker sends commands to the
agent only after marker capture. With the default configuration, the sent command
is the text between `start command` and `send command`.
