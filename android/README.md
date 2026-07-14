# Android WebView shell

This folder contains a small native Android wrapper for Agents Cockpit. The WebView loads the existing `web.py` UI, and `index.html` calls the `AndroidNotify` JavaScript bridge whenever a session enters `confirm`, `plan`, or `done` state.

## Configure

Edit `app/src/main/res/values/strings.xml`:

```xml
<string name="cockpit_url">http://YOUR_PC_LAN_IP:7682/</string>
```

Use the URL printed by `python app.py`. The default `http://10.0.2.2:7682/` is only for the Android emulator.

## Local Build

The repo can use a local SDK/Gradle under `../.local` from this repository root. Build with:

```powershell
.\android\build-local.ps1
```

Output APK:

```text
android/app/build/outputs/apk/debug/app-debug.apk
```

## Android Studio

Open this `android/` folder in Android Studio. If Android Studio does not detect the SDK automatically, set the SDK path to:

```text
E:\tools\codex-web\.local\android-sdk
```

## Notes

- Android 13+ asks for notification permission on first launch.
- Cleartext HTTP is enabled for LAN testing. Prefer HTTPS or a trusted tunnel if exposing the cockpit outside your LAN.
- Because this is a WebView shell, notifications are emitted by the loaded page. If Android kills or freezes the WebView in the background, notification delivery can be delayed; a future fully native background WebSocket service would be more reliable.
