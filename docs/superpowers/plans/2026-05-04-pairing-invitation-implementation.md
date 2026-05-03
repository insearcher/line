# Pairing Invitation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the approved pairing invitation UX and consistent gateway auth model.

**Architecture:** Keep the existing `PairingStore` as trusted-device auth. Add a separate per-process dashboard token in `demo_server.py`, require auth for every sensitive JSON API, expose pairing invitations as deep links, and update iOS to accept invitation links while moving manual connection fields into an advanced path.

**Tech Stack:** Python 3.12 gateway, stdlib HTTP server, pytest, static browser dashboard, SwiftUI iOS app with LiveKit.

---

## File Structure

- Modify `gateway/src/line/pairing.py`: add deep-link formatting for existing pairing sessions.
- Modify `gateway/src/line/demo_server.py`: add dashboard token generation, auth checks for all sensitive JSON APIs, and dashboard URL logging.
- Modify `gateway/src/line/cli.py`: add `--dashboard-token` to `demo-server` and include invitation link in `pair` output through `pairing.py`.
- Modify `gateway/tests/test_pairing.py`: cover deep-link payload and one-time invitation behavior.
- Modify `gateway/tests/test_demo_server.py`: require auth on all sensitive JSON APIs and verify dashboard token behavior.
- Modify `gateway/tests/test_cli.py`: cover the new CLI flag and invitation output behavior where practical.
- Modify `clients/web/index.html`: add a compact dev-token control for the development dashboard.
- Modify `clients/web/app.js`: keep dashboard token in session storage and attach `Authorization` to every JSON request.
- Modify `clients/web/styles.css`: style the dev-token control without changing the dashboard's role.
- Create `clients/ios/Line/GatewayInvitation.swift`: parse `line://pair?...` invitation URLs.
- Create `clients/ios/Line/QRScannerView.swift`: scan QR codes containing invitation links.
- Modify `clients/ios/Line/VoiceClientViewModel.swift`: pair from invitations, handle revoked tokens, and expose advanced setup state.
- Modify `clients/ios/Line/ContentView.swift`: make pairing invitation the main path and move manual fields to advanced disclosure.
- Modify `clients/ios/Line/LineApp.swift`: route custom URL openings into the shared view model.
- Modify `clients/ios/Line/Info.plist` and `clients/ios/project.yml`: add `line://` URL scheme and camera usage description.
- Create `clients/ios/LineTests/GatewayInvitationTests.swift`: cover invitation URL parsing.
- Modify setup and security docs after code behavior is in place.

## Task 1: Baseline Verification

- [ ] **Step 1: Run gateway baseline tests**

Run:

```bash
cd gateway && uv run pytest -q
```

Expected: current test suite passes before behavior changes.

## Task 2: Gateway Auth RED Tests

**Files:**
- Modify: `gateway/tests/test_demo_server.py`

- [ ] **Step 1: Write failing tests for sensitive endpoints**

Add or update tests so unauthenticated requests to these endpoints return `401`:

```python
sensitive_get_paths = [
    "/api/token",
    "/api/events",
    "/api/tasks",
    "/api/usage",
    "/api/agent-runs",
]
```

Also assert unauthenticated `POST /api/reset` returns `401`.

- [ ] **Step 2: Write failing test for dashboard token**

Add a test server with `dashboard_token="test-dashboard-token"` and assert:

```python
headers = {"Authorization": "Bearer test-dashboard-token"}
token_payload = _get_json(f"{base_url}/api/token", headers=headers)
events_payload = _get_json(f"{base_url}/api/events", headers=headers)
reset_payload = _post_json(f"{base_url}/api/reset", headers=headers)
```

The dashboard token should authorize dev JSON APIs but should not create trusted
phones through `/api/pair` without a valid invitation code.

- [ ] **Step 3: Run tests and verify RED**

Run:

```bash
cd gateway && uv run pytest gateway/tests/test_demo_server.py -q
```

Expected: failures show `/api/events`, `/api/tasks`, `/api/usage`, or
`/api/agent-runs` are still unauthenticated, and dashboard token support is
missing.

## Task 3: Gateway Auth Implementation

**Files:**
- Modify: `gateway/src/line/demo_server.py`
- Modify: `gateway/src/line/cli.py`

- [ ] **Step 1: Add dashboard token config**

Extend `DemoServerConfig` with:

```python
dashboard_token: str | None = None
```

Add:

```python
def generate_dashboard_token() -> str:
    return secrets.token_urlsafe(32)
```

Use `dataclasses.replace` in `run_demo_server` so an omitted token is generated
once per server process and printed with a dashboard URL fragment.

- [ ] **Step 2: Add auth checks to all sensitive JSON APIs**

Before serving each sensitive JSON API, call the existing auth helper. The helper
must accept either a trusted phone token or the configured dashboard token:

```python
def _is_authorized(self) -> bool:
    token = self._request_token()
    return _is_dashboard_token(token) or PairingStore(config.pairing_state_path).authenticate(token)
```

- [ ] **Step 3: Add CLI dashboard token flag**

Add:

```python
demo_server.add_argument("--dashboard-token", default=None, help="Optional dev dashboard bearer token.")
```

Pass it into `DemoServerConfig`.

- [ ] **Step 4: Run gateway auth tests and verify GREEN**

Run:

```bash
cd gateway && uv run pytest gateway/tests/test_demo_server.py gateway/tests/test_cli.py -q
```

Expected: tests pass.

## Task 4: Pairing Invitation Deep Link

**Files:**
- Modify: `gateway/src/line/pairing.py`
- Modify: `gateway/tests/test_pairing.py`

- [ ] **Step 1: Write failing test for invitation deep link**

Assert `format_pairing_instructions(session)` includes a `line://pair` URL with
the session server URL, code, gateway device ID, and expiry.

- [ ] **Step 2: Run pairing test and verify RED**

Run:

```bash
cd gateway && uv run pytest gateway/tests/test_pairing.py -q
```

Expected: fails because instructions do not include the deep link yet.

- [ ] **Step 3: Implement deep-link formatting**

Use `urllib.parse.urlencode` to build:

```text
line://pair?serverUrl=<url>&code=<code>&macDeviceId=<id>&expiresAt=<iso>
```

Include both `Deep link:` and `Payload JSON:` in the CLI output.

- [ ] **Step 4: Run pairing tests and verify GREEN**

Run:

```bash
cd gateway && uv run pytest gateway/tests/test_pairing.py gateway/tests/test_cli.py -q
```

Expected: tests pass.

## Task 5: Web Dashboard Dev Token

**Files:**
- Modify: `clients/web/index.html`
- Modify: `clients/web/app.js`
- Modify: `clients/web/styles.css`

- [ ] **Step 1: Update dashboard markup**

Add a small dev auth form near the toolbar:

```html
<form id="auth-form" class="auth-form">
  <input id="dashboard-token" type="password" autocomplete="off" placeholder="Dashboard token" />
  <button id="save-token" type="submit">Use Token</button>
</form>
```

- [ ] **Step 2: Update dashboard fetch helper**

In `app.js`, store the token in `sessionStorage`, parse `location.hash` for
`dashboardToken`, and attach:

```javascript
headers.Authorization = `Bearer ${dashboardToken}`;
```

to every JSON request when present.

- [ ] **Step 3: Handle unauthorized dashboard state**

When a JSON request returns `401`, keep the dashboard visible but log that the dev
token is required and stop treating polling errors as fatal UI noise.

## Task 6: iOS Invitation Parsing RED Tests

**Files:**
- Create: `clients/ios/Line/GatewayInvitation.swift`
- Create: `clients/ios/LineTests/GatewayInvitationTests.swift`

- [ ] **Step 1: Write parser tests**

Add tests for:

```swift
line://pair?serverUrl=http%3A%2F%2F192.0.2.10%3A8787&code=ABCD-2345&macDeviceId=mac-1&expiresAt=2026-05-04T10%3A00%3A00Z
```

Expected values:

```swift
serverURL.absoluteString == "http://192.0.2.10:8787"
code == "ABCD-2345"
macDeviceId == "mac-1"
```

- [ ] **Step 2: Run iOS parser tests and verify RED**

Run:

```bash
cd clients/ios && xcodebuild test -project Line.xcodeproj -scheme Line -destination 'platform=iOS Simulator,name=iPhone 15,OS=17.0.1' -only-testing:LineTests/GatewayInvitationTests
```

Expected: fails because the parser does not exist yet, or the simulator is not
available; if simulator is unavailable, record the exact error and continue with
gateway verification.

## Task 7: iOS Invitation Implementation

**Files:**
- Create: `clients/ios/Line/GatewayInvitation.swift`
- Create: `clients/ios/Line/QRScannerView.swift`
- Modify: `clients/ios/Line/LineApp.swift`
- Modify: `clients/ios/Line/VoiceClientViewModel.swift`
- Modify: `clients/ios/Line/ContentView.swift`
- Modify: `clients/ios/Line/Info.plist`
- Modify: `clients/ios/project.yml`

- [ ] **Step 1: Implement `GatewayInvitation`**

Parse only `line://pair` URLs with non-empty `serverUrl` and `code`. Reject other
schemes or missing fields with a user-facing error.

- [ ] **Step 2: Implement QR scanner sheet**

Use `AVCaptureSession` with metadata type `.qr`, call back with the scanned
string, and let the view model parse it as an invitation URL.

- [ ] **Step 3: Wire shared model and URL scheme**

Make `LineApp` own a single `VoiceClientViewModel`, pass it into `ContentView`,
and handle `.onOpenURL`.

- [ ] **Step 4: Move manual fields to advanced UI**

Keep URL, identity, room override, and pairing code fields available, but put
them behind an advanced disclosure. Main path shows a scan invitation action.

- [ ] **Step 5: Add URL scheme and camera usage**

Add `line` URL scheme and `NSCameraUsageDescription` to both `Info.plist` and
`project.yml`.

- [ ] **Step 6: Run iOS checks**

Run the parser test command from Task 6. If the configured simulator is
unavailable, run:

```bash
cd clients/ios && xcodebuild -project Line.xcodeproj -scheme Line -showdestinations
```

and report the environment limitation.

## Task 8: Docs and Final Verification

**Files:**
- Modify: `README.md`
- Modify: `docs/server-setup.md`
- Modify: `docs/ios-build.md`
- Modify: `docs/security.md`
- Modify: `SECURITY.md`

- [ ] **Step 1: Update docs**

Replace the default manual pairing instructions with gateway invitation and
document the advanced manual fallback.

- [ ] **Step 2: Run gateway full test suite**

Run:

```bash
cd gateway && uv run pytest -q
```

Expected: all gateway tests pass.

- [ ] **Step 3: Run iOS verification or capture limitation**

Run:

```bash
cd clients/ios && xcodebuild test -project Line.xcodeproj -scheme Line -destination 'platform=iOS Simulator,name=iPhone 15,OS=17.0.1'
```

Expected: iOS tests pass, or the final report names the exact simulator/tooling
limitation.

- [ ] **Step 4: Inspect git diff**

Run:

```bash
git diff --stat
git status --short
```

Expected: only planned files changed.
