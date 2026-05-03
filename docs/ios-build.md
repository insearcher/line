# iOS Build

The iOS app is source-built for the v0.1 release. It connects to the local demo
server, joins the LiveKit room, applies local energy VAD, and plays remote agent
audio.

## Requirements

- Xcode 15+
- XcodeGen
- iOS 17+
- A physical iPhone for the intended workflow

## Generate the project

```bash
cd ios/Line
xcodegen generate
open Line.xcodeproj
```

The checked-in scheme is `Line`; the public app display name is `line`.

## Signing

The checked-in project intentionally does not include a personal Apple
development team. Put local signing values in the ignored file
`ios/Line/Line.local.xcconfig`:

```xcconfig
LINE_DEVELOPMENT_TEAM =
LINE_PRODUCT_BUNDLE_IDENTIFIER =
LINE_TEST_PRODUCT_BUNDLE_IDENTIFIER =
```

Fill those values with your Apple team and bundle identifiers, then regenerate
the project:

```bash
cd ios/Line
xcodegen generate
open Line.xcodeproj
```

Do not commit `Line.local.xcconfig`.

## Pairing

Start the server on your Mac:

```bash
uv run line demo-server --host 0.0.0.0 --room line-dev --identity mac-test
```

Create a pairing code:

```bash
uv run line pair --server-url http://YOUR-MAC-LAN-IP:8787
```

In the app, enter the pairing code and connect. The app stores the phone token in
the Keychain. Use the key-slash button in the app to forget the token and pair
again.

## Simulator

The simulator can use `http://127.0.0.1:8787` as the server URL. Physical iPhones
need a reachable LAN or private VPN address.

## Tests

```bash
xcodebuild test \
  -project ios/Line/Line.xcodeproj \
  -scheme Line \
  -destination 'platform=iOS Simulator,name=iPhone 15,OS=17.0.1'
```

If your Xcode installation does not have that simulator runtime, select an
available iOS 17+ simulator in Xcode and adjust the destination.
