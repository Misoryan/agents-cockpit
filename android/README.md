# Android WebView shell

This folder contains a small native Android wrapper for Agents Cockpit. The WebView loads the existing `web.py` UI, and `index.html` calls the `AndroidNotify` JavaScript bridge whenever a session enters `confirm`, `plan`, or `done` state.

The wrapper also starts a foreground keep-alive service. It keeps the process warm, saves/restores WebView state, and polls `/api/sessions` with the WebView login cookie so confirmation / plan / done notifications can still arrive when Android freezes the page in the background.

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
- Android will show an ongoing "Agents Cockpit 保持连接" notification while background keep-alive is active. Disable battery optimization for the app if your ROM still kills foreground services aggressively.
- Cleartext HTTP is enabled for LAN testing. Prefer HTTPS or a trusted tunnel if exposing the cockpit outside your LAN.
- Because this is still a WebView shell, Android may reclaim it under extreme memory pressure. The foreground service prevents the common "background for a while then refresh and lose page-emitted notifications" case; a future native WebSocket client could make this fully independent of WebView lifecycle.
