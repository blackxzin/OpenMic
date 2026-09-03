# Installing the iOS app yourself

There is no App Store build and no TestFlight link: both need a paid Apple Developer
account, which this project doesn't have. CI compiles the iOS app on every push
(`.github/workflows/ios-build-check.yml`) so it's known to build — it just can't be
signed and distributed from here.

Until that changes, you can build and install it yourself. Everything below needs a Mac.

## What you need

- A Mac with **Xcode** installed (free from the App Store).
- Any Apple ID. A **free** account works — no paid membership needed.
- A USB cable for the iPhone.

## Build and install

```bash
git clone https://github.com/blackxzin/OpenMic.git
cd OpenMic/mobile
flutter pub get
cd ios && pod install && cd ..
```

Then open the Xcode workspace and let Xcode handle signing:

```bash
open ios/Runner.xcworkspace
```

In Xcode:

1. Select the **Runner** target → **Signing & Capabilities**.
2. Tick **Automatically manage signing**.
3. In **Team**, add your Apple ID (Xcode → Settings → Accounts → `+`) and select it.
4. Change **Bundle Identifier** to something unique to you, e.g. `com.yourname.openmic`.
   A free account can't reuse someone else's identifier.
5. Plug in the iPhone, pick it as the run destination, and press **Run** (⌘R).

The first launch fails with "Untrusted Developer" until you approve the certificate on the
phone: **Settings → General → VPN & Device Management → your Apple ID → Trust**.

Or from the command line, once signing is configured in Xcode:

```bash
flutter run --release -d <device-id>   # flutter devices lists the ids
```

## Free-account limits

- The app **expires after 7 days**. Rebuild and reinstall to renew it — the pairing
  credentials in the keychain survive, so you won't have to pair again.
- Up to 3 apps signed with a free account can be installed at once.
- A paid account ($99/year) raises the expiry to a year and enables TestFlight.

## Microphone permission

iOS asks for microphone access on the first connect. If you deny it by accident, re-enable
it in **Settings → OpenMic → Microphone** — the app can't ask twice.

## What works on iOS

Discovery (Bonjour), pairing, Opus streaming, the quality selector and the VU meter all
work the same as on Android. Background streaming differs in mechanism: Android runs a
foreground service with a persistent notification, while iOS relies on the `audio`
background mode declared in `Info.plist` to keep the capture session alive with the screen
locked. iOS shows no permanent notification for it.
