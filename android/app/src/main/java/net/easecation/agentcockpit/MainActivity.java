package net.easecation.agentcockpit;

import android.Manifest;
import android.app.Activity;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.ActivityNotFoundException;
import android.content.ClipData;
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
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebBackForwardList;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.webkit.WebResourceRequest;


import java.util.ArrayList;

import org.json.JSONObject;

public class MainActivity extends Activity {
    private static final String CHANNEL_ID = "agent_events";
    private static final int REQ_NOTIFY = 41;
    private static final int REQ_FILE_CHOOSER = 42;

    private WebView webView;
    private FrameLayout rootView;
    private String baseUrl;
    private boolean pageLoaded = false;
    private ValueCallback<Uri[]> filePathCallback;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        baseUrl = normalizeBaseUrl(getString(R.string.cockpit_url));
        createNotificationChannel();
        requestNotificationPermission();
        startKeepAliveService();

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
        if (savedInstanceState != null) {
            WebBackForwardList restored = webView.restoreState(savedInstanceState);
            if (restored == null || restored.getSize() == 0) {
                loadUrlForIntent(getIntent());
                return;
            }
            pageLoaded = true;
        } else {
            loadUrlForIntent(getIntent());
        }
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
        settings.setCacheMode(WebSettings.LOAD_DEFAULT);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
        settings.setUserAgentString(settings.getUserAgentString() + " AgentsCockpitAndroid/0.1");
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            settings.setOffscreenPreRaster(true);
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            webView.setRendererPriorityPolicy(WebView.RENDERER_PRIORITY_IMPORTANT, false);
        }

        webView.addJavascriptInterface(new NotifyBridge(), "AndroidNotify");
        webView.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback, FileChooserParams params) {
                if (filePathCallback != null) {
                    filePathCallback.onReceiveValue(null);
                }
                filePathCallback = callback;
                Intent intent = buildFileChooserIntent(params);
                try {
                    startActivityForResult(intent, REQ_FILE_CHOOSER);
                    return true;
                } catch (ActivityNotFoundException e) {
                    filePathCallback = null;
                    callback.onReceiveValue(null);
                    return false;
                }
            }
        });
        webView.setWebViewClient(new WebViewClient() {
            @Override
            public void onPageFinished(WebView view, String url) {
                pageLoaded = true;
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

    private Intent buildFileChooserIntent(WebChromeClient.FileChooserParams params) {
        Intent intent = null;
        if (params != null) {
            try {
                intent = params.createIntent();
            } catch (Exception ignored) {
            }
        }
        if (intent == null) {
            intent = new Intent(Intent.ACTION_GET_CONTENT);
            intent.addCategory(Intent.CATEGORY_OPENABLE);
        }
        applyAcceptTypes(intent, params);
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
        boolean allowMultiple = params != null
                && params.getMode() == WebChromeClient.FileChooserParams.MODE_OPEN_MULTIPLE;
        intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, allowMultiple);
        return Intent.createChooser(intent, "Select image");
    }

    private void applyAcceptTypes(Intent intent, WebChromeClient.FileChooserParams params) {
        ArrayList<String> accepts = new ArrayList<>();
        if (params != null && params.getAcceptTypes() != null) {
            for (String accept : params.getAcceptTypes()) {
                if (accept != null) {
                    String trimmed = accept.trim();
                    if (!trimmed.isEmpty() && !accepts.contains(trimmed)) {
                        accepts.add(trimmed);
                    }
                }
            }
        }
        if (accepts.size() == 1) {
            intent.setType(accepts.get(0));
        } else if (accepts.size() > 1) {
            intent.setType("*/*");
            intent.putExtra(Intent.EXTRA_MIME_TYPES, accepts.toArray(new String[0]));
        } else if (intent.getType() == null || intent.getType().isEmpty() || "*/*".equals(intent.getType())) {
            intent.setType("image/*");
        }
    }

    private Uri[] collectFileChooserUris(int resultCode, Intent data) {
        if (resultCode != RESULT_OK) return null;
        ArrayList<Uri> uris = new ArrayList<>();
        if (data != null) {
            ClipData clipData = data.getClipData();
            if (clipData != null) {
                for (int i = 0; i < clipData.getItemCount(); i += 1) {
                    Uri uri = clipData.getItemAt(i).getUri();
                    if (uri != null && !uris.contains(uri)) uris.add(uri);
                }
            }
            Uri dataUri = data.getData();
            if (dataUri != null && !uris.contains(dataUri)) uris.add(dataUri);
        }
        if (!uris.isEmpty()) return uris.toArray(new Uri[0]);
        return WebChromeClient.FileChooserParams.parseResult(resultCode, data);
    }

    private void loadUrlForIntent(Intent intent) {
        String sid = intent == null ? "" : intent.getStringExtra("sid");
        String url = baseUrl;
        if (sid != null && !sid.isEmpty()) {
            if (pageLoaded) {
                openSessionInPage(sid);
                return;
            }
            url += "?open=" + Uri.encode(sid);
        } else if (pageLoaded && webView != null && webView.getUrl() != null) {
            return;
        }
        webView.loadUrl(url);
    }

    private void openSessionInPage(String sid) {
        if (webView == null || sid == null || sid.isEmpty()) return;
        String js = "(function(){if(window.openSessionBySid){openSessionBySid("
                + JSONObject.quote(sid) + ",true);}})();";
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.KITKAT) {
            webView.evaluateJavascript(js, null);
        } else {
            webView.loadUrl("javascript:" + js);
        }
    }

    private void startKeepAliveService() {
        Intent service = new Intent(this, KeepAliveService.class);
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                startForegroundService(service);
            } else {
                startService(service);
            }
        } catch (Exception ignored) {
        }
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
        NotificationChannel channel = new NotificationChannel(CHANNEL_ID, "Agent 通知", NotificationManager.IMPORTANCE_HIGH);
        channel.setDescription("Codex / Claude 的确认、计划审阅和完成提醒");
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
                .setLargeIcon(NotificationLogo.largeIcon(this))
                .setColor(NotificationLogo.ACCENT_COLOR)
                .setContentTitle(title == null || title.isEmpty() ? "Agent 通知" : title)
                .setContentText(body == null ? "" : body)
                .setStyle(new Notification.BigTextStyle().bigText(body == null ? "" : body))
                .setAutoCancel(true)
                .setContentIntent(pendingIntent)
                .setPriority(priority);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            builder.setBadgeIconType(Notification.BADGE_ICON_LARGE);
        }
        NotificationManager manager = (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
        if (manager != null) {
            AndroidNoticeStore.mark(this, sid, kind);
            manager.notify((sid + kind).hashCode(), builder.build());
        }
    }

    @Override
    protected void onResume() {
        super.onResume();
        startKeepAliveService();
        if (webView != null) {
            webView.onResume();
            webView.resumeTimers();
        }
    }

    @Override
    protected void onPause() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
            CookieManager.getInstance().flush();
        }
        startKeepAliveService();
        super.onPause();
    }

    @Override
    protected void onSaveInstanceState(Bundle outState) {
        if (webView != null) {
            webView.saveState(outState);
        }
        super.onSaveInstanceState(outState);
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        if (requestCode == REQ_FILE_CHOOSER) {
            ValueCallback<Uri[]> callback = filePathCallback;
            filePathCallback = null;
            if (callback != null) {
                callback.onReceiveValue(collectFileChooserUris(resultCode, data));
            }
            return;
        }
        super.onActivityResult(requestCode, resultCode, data);
    }

    @Override
    protected void onDestroy() {
        if (filePathCallback != null) {
            filePathCallback.onReceiveValue(null);
            filePathCallback = null;
        }
        super.onDestroy();
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
                String title = json.optString("title", "Agent 通知");
                String body = json.optString("body", "");
                runOnUiThread(() -> showNotification(kind, sid, title, body));
            } catch (Exception ignored) {
            }
        }
    }
}
