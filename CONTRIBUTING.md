# Contributing

line is an early developer tool. The first release target is narrow: build the
macOS server and iOS app from source, pair a phone, speak a marker-gated command,
and receive a spoken response from a local Codex app-server session.

## Development setup

```bash
uv sync --all-extras --dev
uv run pytest -q
```

For the optional Claude channel bridge:

```bash
cd channels/claude-voice-channel
bun install
bun test
```

For the iOS app, install Xcode and XcodeGen, then generate and test the project:

```bash
cd ios/Line
xcodegen generate
xcodebuild test -project Line.xcodeproj -scheme Line -destination 'platform=iOS Simulator,name=iPhone 15,OS=17.0.1'
```

## Pull requests

- Keep changes focused on one behavior or documentation area.
- Add or update tests for Python, Swift, or TypeScript behavior changes.
- Do not commit `.env`, local pairing state, logs, room tokens, API keys, or
  generated runtime files under `data/`.
- Keep the public happy path centered on Codex app-server. Document other agent
  backends as advanced or experimental until they are productized.

## Code style

The project currently uses the standard Python, Swift, and TypeScript toolchains
without an additional formatter mandate. Match the surrounding style and keep
public docs copy-pasteable from a fresh clone.
