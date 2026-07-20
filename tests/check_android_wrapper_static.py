"""Static checks for the Android WebView wrapper."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main():
    main_activity = (ROOT / "android/app/src/main/java/net/easecation/agentcockpit/MainActivity.java").read_text(encoding="utf-8")
    keep_alive = (ROOT / "android/app/src/main/java/net/easecation/agentcockpit/KeepAliveService.java").read_text(encoding="utf-8")
    notification_logo = (ROOT / "android/app/src/main/java/net/easecation/agentcockpit/NotificationLogo.java").read_text(encoding="utf-8")
    manifest = (ROOT / "android/app/src/main/AndroidManifest.xml").read_text(encoding="utf-8")
    gradle = (ROOT / "android/app/build.gradle").read_text(encoding="utf-8")
    logo = (ROOT / "assets/agent-cockpit-logo.svg").read_text(encoding="utf-8")

    assert "startKeepAliveService()" in main_activity
    assert "startForegroundService(service)" in main_activity
    assert "webView.saveState(outState)" in main_activity
    assert "webView.restoreState(savedInstanceState)" in main_activity
    assert "setRendererPriorityPolicy(WebView.RENDERER_PRIORITY_IMPORTANT, false)" in main_activity
    assert "onShowFileChooser" in main_activity
    assert "REQ_FILE_CHOOSER" in main_activity
    assert "Intent.EXTRA_ALLOW_MULTIPLE" in main_activity
    assert "collectFileChooserUris(resultCode, data)" in main_activity
    assert "openSessionBySid" in main_activity
    assert "setLargeIcon(NotificationLogo.largeIcon(this))" in main_activity
    assert "setColor(NotificationLogo.ACCENT_COLOR)" in main_activity
    assert "setBadgeIconType(Notification.BADGE_ICON_LARGE)" in main_activity

    assert 'android:name=".KeepAliveService"' in manifest
    assert 'android:foregroundServiceType="dataSync"' in manifest
    assert "android.permission.FOREGROUND_SERVICE_DATA_SYNC" in manifest
    assert "android.permission.WAKE_LOCK" in manifest
    assert 'android:icon="@drawable/ic_launcher_agent"' in manifest
    assert 'android:launchMode="singleTop"' in manifest

    assert "START_STICKY" in keep_alive
    assert "PowerManager.PARTIAL_WAKE_LOCK" in keep_alive
    assert 'joinUrl(baseUrl, "api/sessions")' in keep_alive
    assert "CookieManager.getInstance().getCookie(baseUrl)" in keep_alive
    assert "AndroidNoticeStore.recentlyNotified" in keep_alive
    assert "FOREGROUND_SERVICE_TYPE_DATA_SYNC" in keep_alive
    assert "setLargeIcon(NotificationLogo.largeIcon(this))" in keep_alive
    assert "setColor(NotificationLogo.ACCENT_COLOR)" in keep_alive

    assert "Drawable drawable = context.getDrawable(R.drawable.ic_launcher_agent)" in notification_logo
    assert "Bitmap.createBitmap" in notification_logo

    assert "versionCode 6" in gradle
    assert "versionName '0.1.5'" in gradle
    assert "<svg" in logo and "Agents Cockpit logo" in logo

    print("android wrapper static checks passed")


if __name__ == "__main__":
    main()
