package net.easecation.agentcockpit;

import android.Manifest;
import android.app.Activity;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.view.View;
import android.view.Window;
import android.view.WindowManager;
import android.widget.FrameLayout;
import android.webkit.CookieManager;
import android.webkit.JavascriptInterface;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.webkit.WebResourceRequest;


import org.json.JSONObject;

public class MainActivity extends Activity {
    private static final String CHANNEL_ID = "agent_events";
    private static final int REQ_NOTIFY = 41;

    private WebView webView;
    private FrameLayout rootView;
    private String baseUrl;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        baseUrl = normalizeBaseUrl(getString(R.string.cockpit_url));
        createNotificationChannel();
        requestNotificationPermission();

        Window window = getWindow();
        window.clearFlags(WindowManager.LayoutParams.FLAG_FULLSCREEN
                | WindowManager.LayoutParams.FLAG_TRANSLUCENT_STATUS
                | WindowManager.LayoutParams.FLAG_TRANSLUCENT_NAVIGATION
                | WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS);
        window.addFlags(WindowManager.LayoutParams.FLAG_DRAWS_SYSTEM_BAR_BACKGROUNDS);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            window.setDecorFitsSystemWindows(true);
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            window.getAttributes().layoutInDisplayCutoutMode = WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_NEVER;
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            window.getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR);
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
            window.setStatusBarColor(0xfff7f4ed);
            window.setNavigationBarColor(0xfff7f4ed);
        }

        webView = new WebView(this);
        rootView = new FrameLayout(this);
        rootView.setBackgroundColor(0xfff7f4ed);
        rootView.setFitsSystemWindows(false);
        rootView.addView(webView, new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT));
        setContentView(rootView);
        configureWebView();
        loadUrlForIntent(getIntent());
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        loadUrlForIntent(intent);
    }

    private void configureWebView() {
        CookieManager.getInstance().setAcceptCookie(true);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
            CookieManager.getInstance().setAcceptThirdPartyCookies(webView, true);
        }

        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        settings.setMediaPlaybackRequiresUserGesture(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
        settings.setUserAgentString(settings.getUserAgentString() + " AgentsCockpitAndroid/0.1");

        webView.addJavascriptInterface(new NotifyBridge(), "AndroidNotify");
        webView.setWebChromeClient(new WebChromeClient());
        webView.setWebViewClient(new WebViewClient() {
            @Override
            public void onPageFinished(WebView view, String url) {
                injectStatusBarSpacer();
            }

            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri uri = request.getUrl();
                if (uri != null && ("http".equals(uri.getScheme()) || "https".equals(uri.getScheme()))) {
                    return false;
                }
                try {
                    startActivity(new Intent(Intent.ACTION_VIEW, uri));
                    return true;
                } catch (Exception ignored) {
                    return true;
                }
            }
        });
    }

    private void loadUrlForIntent(Intent intent) {
        String sid = intent == null ? "" : intent.getStringExtra("sid");
        String url = baseUrl;
        if (sid != null && !sid.isEmpty()) {
            url += "?open=" + Uri.encode(sid);
        }
        webView.loadUrl(url);
    }

    private void injectStatusBarSpacer() {
        if (webView == null) return;
        String js = "(function(){" +
                "var id='android-windowed-fix';" +
                "var el=document.getElementById(id);" +
                "if(!el){el=document.createElement('style');el.id=id;document.head.appendChild(el);}" +
                "el.textContent='html,body{min-height:100%!important;}';" +
                "})();";
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.KITKAT) {
            webView.evaluateJavascript(js, null);
        } else {
            webView.loadUrl("javascript:" + js);
        }
    }

    private String normalizeBaseUrl(String url) {
        if (url == null || url.trim().isEmpty()) return "http://10.0.2.2:7682/";
        String trimmed = url.trim();
        return trimmed.endsWith("/") ? trimmed : trimmed + "/";
    }

    private void requestNotificationPermission() {
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, REQ_NOTIFY);
        }
    }

    private void createNotificationChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return;
        NotificationChannel channel = new NotificationChannel(CHANNEL_ID, "Agent events", NotificationManager.IMPORTANCE_HIGH);
        channel.setDescription("Codex / Claude confirmation and completion events");
        NotificationManager manager = (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
        if (manager != null) manager.createNotificationChannel(channel);
    }

    private void showNotification(String kind, String sid, String title, String body) {
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestNotificationPermission();
            return;
        }
        Intent intent = new Intent(this, MainActivity.class);
        intent.setFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        intent.putExtra("sid", sid == null ? "" : sid);
        int flags = PendingIntent.FLAG_UPDATE_CURRENT;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) flags |= PendingIntent.FLAG_IMMUTABLE;
        PendingIntent pendingIntent = PendingIntent.getActivity(this, (sid == null ? "" : sid).hashCode(), intent, flags);

        int icon = R.drawable.ic_stat_agent;
        int priority = Notification.PRIORITY_DEFAULT;
        if ("confirm".equals(kind) || "plan".equals(kind)) {
            icon = R.drawable.ic_stat_agent;
            priority = Notification.PRIORITY_HIGH;
        }

        Notification.Builder builder = Build.VERSION.SDK_INT >= Build.VERSION_CODES.O
                ? new Notification.Builder(this, CHANNEL_ID)
                : new Notification.Builder(this);
        builder.setSmallIcon(icon)
                .setContentTitle(title == null || title.isEmpty() ? "Agent event" : title)
                .setContentText(body == null ? "" : body)
                .setStyle(new Notification.BigTextStyle().bigText(body == null ? "" : body))
                .setAutoCancel(true)
                .setContentIntent(pendingIntent)
                .setPriority(priority);
        NotificationManager manager = (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
        if (manager != null) manager.notify((sid + kind).hashCode(), builder.build());
    }

    @Override
    public void onBackPressed() {
        if (webView != null && webView.canGoBack()) {
            webView.goBack();
        } else {
            super.onBackPressed();
        }
    }

    public class NotifyBridge {
        @JavascriptInterface
        public void notify(String payload) {
            try {
                JSONObject json = new JSONObject(payload == null ? "{}" : payload);
                String kind = json.optString("kind", "event");
                String sid = json.optString("sid", "");
                String title = json.optString("title", "Agent event");
                String body = json.optString("body", "");
                runOnUiThread(() -> showNotification(kind, sid, title, body));
            } catch (Exception ignored) {
            }
        }
    }
}





