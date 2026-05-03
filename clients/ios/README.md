# iOS Client

The iOS app is source-built for the v0.1 release. It connects to the local demo
gateway, joins the LiveKit room, applies local energy VAD, and plays remote agent
audio.

Run commands from this directory unless another directory is shown.

## Requirements

- Xcode 15+
- XcodeGen
- iOS 17+
- A physical iPhone for the intended workflow

## Generate the project

```bash
xcodegen generate
open Line.xcodeproj
```

The checked-in scheme is `Line`; the public app display name is `line`.

## Signing

The checked-in project intentionally does not include a personal Apple
development team. Put local signing values in the ignored file
`Line.local.xcconfig` in this directory:

```xcconfig
LINE_DEVELOPMENT_TEAM =
LINE_PRODUCT_BUNDLE_IDENTIFIER =
LINE_TEST_PRODUCT_BUNDLE_IDENTIFIER =
```

Fill those values with your Apple team and bundle identifiers, then regenerate
the project:

```bash
xcodegen generate
open Line.xcodeproj
```

Do not commit `Line.local.xcconfig`.

## Pairing

From the repository root, start the gateway on your Mac:

```bash
cd gateway
uv run line demo-server --host 0.0.0.0 --room line-dev --identity mac-test
```

From the repository root, create a gateway invitation:

```bash
cd gateway
uv run line pair --server-url http://YOUR-MAC-LAN-IP:8787
```

In the app, use Scan Gateway Invitation and scan the printed QR code. You can
also open the printed `line://pair` deep link on the phone. The app stores the
phone token in the Keychain. Use the key-slash button in the app to forget the
token and pair again.

Manual server URL and pairing-code entry are still available in Advanced for
debugging and simulator workflows.

## Simulator

The simulator can use `http://127.0.0.1:8787` as the server URL. Physical iPhones
need a reachable LAN or private VPN address.

## Tests

```bash
xcodebuild test \
  -project Line.xcodeproj \
  -scheme Line \
  -destination 'platform=iOS Simulator,name=iPhone 15,OS=17.0.1'
```

If your Xcode installation does not have that simulator runtime, select an
available iOS 17+ simulator in Xcode and adjust the destination.
