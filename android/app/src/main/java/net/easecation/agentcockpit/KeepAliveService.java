package net.easecation.agentcockpit;

import android.Manifest;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.content.pm.ServiceInfo;
import android.net.Uri;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.PowerManager;
import android.webkit.CookieManager;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Iterator;
import java.util.Map;
import java.util.Set;

public class KeepAliveService extends Service {
    private static final String KEEP_CHANNEL_ID = "agent_keepalive";
    private static final String EVENT_CHANNEL_ID = "agent_events";
    private static final int KEEP_NOTIFICATION_ID = 8801;
    private static final long POLL_MS = 25_000L;
    private static final long DEDUPE_MS = 120_000L;

    private final Handler handler = new Handler(Looper.getMainLooper());
    private final Map<String, String> lastStates = new HashMap<>();
    private PowerManager.WakeLock wakeLock;
    private String baseUrl;
    private volatile boolean pollInFlight = false;

    private final Runnable pollLoop = new Runnable() {
        @Override
        public void run() {
            pollSessions();
            handler.postDelayed(this, POLL_MS);
        }
    };

    @Override
    public void onCreate() {
        super.onCreate();
        baseUrl = normalizeBaseUrl(getString(R.string.cockpit_url));
        createNotificationChannels();
        acquireWakeLock();
        startAsForeground();
        handler.post(pollLoop);
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null && intent.getStringExtra("base_url") != null) {
            baseUrl = normalizeBaseUrl(intent.getStringExtra("base_url"));
        }
        startAsForeground();
        return START_STICKY;
    }

    @Override
    public void onDestroy() {
        handler.removeCallbacksAndMessages(null);
        if (wakeLock != null && wakeLock.isHeld()) {
            wakeLock.release();
        }
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    private void startAsForeground() {
        Notification notification = keepAliveNotification();
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(KEEP_NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC);
        } else {
            startForeground(KEEP_NOTIFICATION_ID, notification);
        }
    }

    private void acquireWakeLock() {
        try {
            PowerManager pm = (PowerManager) getSystemService(Context.POWER_SERVICE);
            if (pm == null) return;
            wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "AgentCockpit:KeepAlive");
            wakeLock.setReferenceCounted(false);
            wakeLock.acquire();
        } catch (Exception ignored) {
        }
    }

    private void pollSessions() {
        if (pollInFlight) return;
        pollInFlight = true;
        new Thread(() -> {
            try {
                handleSessions(fetchJson(joinUrl(baseUrl, "api/sessions")));
            } catch (Exception ignored) {
            } finally {
                pollInFlight = false;
            }
        }, "agent-session-poll").start();
    }

    private void handleSessions(JSONObject json) {
        JSONArray sessions = json == null ? null : json.optJSONArray("sessions");
        if (sessions == null) return;
        Set<String> seen = new HashSet<>();
        for (int i = 0; i < sessions.length(); i++) {
            JSONObject s = sessions.optJSONObject(i);
            if (s == null) continue;
            String sid = s.optString("sid", "");
            String state = s.optString("state", "idle");
            if (sid.isEmpty()) continue;
            seen.add(sid);
            String prev = lastStates.get(sid);
            if ("confirm".equals(state) && !"confirm".equals(prev)) {
                notifyEvent("confirm", s);
            } else if ("plan".equals(state) && !"plan".equals(prev)) {
                notifyEvent("plan", s);
            } else if ("idle".equals(state) && prev != null && !"idle".equals(prev) && !"new".equals(prev)) {
                notifyEvent("done", s);
            }
            lastStates.put(sid, state);
        }
        Iterator<String> it = lastStates.keySet().iterator();
        while (it.hasNext()) {
            if (!seen.contains(it.next())) it.remove();
        }
    }

    private JSONObject fetchJson(String url) throws Exception {
        HttpURLConnection conn = (HttpURLConnection) new URL(url).openConnection();
        conn.setConnectTimeout(8_000);
        conn.setReadTimeout(12_000);
        conn.setRequestProperty("Accept", "application/json");
        String cookies = CookieManager.getInstance().getCookie(baseUrl);
        if (cookies != null && !cookies.isEmpty()) {
            conn.setRequestProperty("Cookie", cookies);
        }
        int status = conn.getResponseCode();
        InputStream stream = status >= 200 && status < 400 ? conn.getInputStream() : conn.getErrorStream();
        String body = readAll(stream);
        conn.disconnect();
        if (status < 200 || status >= 400) throw new IllegalStateException("HTTP " + status);
        return new JSONObject(body);
    }

    private String readAll(InputStream stream) throws Exception {
        if (stream == null) return "";
        BufferedReader reader = new BufferedReader(new InputStreamReader(stream, StandardCharsets.UTF_8));
        StringBuilder out = new StringBuilder();
        String line;
        while ((line = reader.readLine()) != null) {
            out.append(line).append('\n');
        }
        return out.toString();
    }

    private void notifyEvent(String kind, JSONObject s) {
        String sid = s.optString("sid", "");
        if (AndroidNoticeStore.recentlyNotified(this, sid, kind, DEDUPE_MS)) return;
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            return;
        }
        String task = sessionTitle(s);
        String project = basename(s.optString("dir", ""));
        String backend = backendLabel(s.optString("backend", ""));
        String title = eventLabel(kind) + " · " + task;
        String body = backend + " · " + (project.isEmpty() ? "当前会话" : project) + "\n" + eventHint(kind);
        Notification.Builder builder = Build.VERSION.SDK_INT >= Build.VERSION_CODES.O
                ? new Notification.Builder(this, EVENT_CHANNEL_ID)
                : new Notification.Builder(this);
        builder.setSmallIcon(R.drawable.ic_stat_agent)
                .setLargeIcon(NotificationLogo.largeIcon(this))
                .setColor(NotificationLogo.ACCENT_COLOR)
                .setContentTitle(title)
                .setContentText(body)
                .setStyle(new Notification.BigTextStyle().bigText(body))
                .setAutoCancel(true)
                .setContentIntent(openSessionIntent(sid))
                .setPriority(("confirm".equals(kind) || "plan".equals(kind)) ? Notification.PRIORITY_HIGH : Notification.PRIORITY_DEFAULT);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            builder.setBadgeIconType(Notification.BADGE_ICON_LARGE);
        }
        NotificationManager manager = (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
        if (manager != null) {
            AndroidNoticeStore.mark(this, sid, kind);
            manager.notify((sid + kind).hashCode(), builder.build());
        }
    }

    private PendingIntent openSessionIntent(String sid) {
        Intent intent = new Intent(this, MainActivity.class);
        intent.setFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        intent.putExtra("sid", sid == null ? "" : sid);
        int flags = PendingIntent.FLAG_UPDATE_CURRENT;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) flags |= PendingIntent.FLAG_IMMUTABLE;
        return PendingIntent.getActivity(this, (sid == null ? "" : sid).hashCode(), intent, flags);
    }

    private Notification keepAliveNotification() {
        Notification.Builder builder = Build.VERSION.SDK_INT >= Build.VERSION_CODES.O
                ? new Notification.Builder(this, KEEP_CHANNEL_ID)
                : new Notification.Builder(this);
        return builder.setSmallIcon(R.drawable.ic_stat_agent)
                .setLargeIcon(NotificationLogo.largeIcon(this))
                .setColor(NotificationLogo.ACCENT_COLOR)
                .setContentTitle("Agents Cockpit 保持连接")
                .setContentText("后台持续同步会话状态和待确认提醒")
                .setOngoing(true)
                .setContentIntent(openSessionIntent(""))
                .setPriority(Notification.PRIORITY_LOW)
                .build();
    }

    private void createNotificationChannels() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return;
        NotificationManager manager = (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
        if (manager == null) return;
        NotificationChannel keep = new NotificationChannel(KEEP_CHANNEL_ID, "后台保活", NotificationManager.IMPORTANCE_LOW);
        keep.setDescription("保持 WebView 进程与会话状态轮询，减少后台返回后整页刷新");
        NotificationChannel events = new NotificationChannel(EVENT_CHANNEL_ID, "Agent 通知", NotificationManager.IMPORTANCE_HIGH);
        events.setDescription("Codex / Claude 的确认、计划审阅和完成提醒");
        manager.createNotificationChannel(keep);
        manager.createNotificationChannel(events);
    }

    private String normalizeBaseUrl(String url) {
        if (url == null || url.trim().isEmpty()) return "http://10.0.2.2:7682/";
        String trimmed = url.trim();
        return trimmed.endsWith("/") ? trimmed : trimmed + "/";
    }

    private String joinUrl(String base, String path) {
        return normalizeBaseUrl(base) + path;
    }

    private String sessionTitle(JSONObject s) {
        String title = s.optString("title", "").trim();
        if (!title.isEmpty()) return title;
        String dir = s.optString("dir", "");
        String name = basename(dir);
        return name.isEmpty() ? "未命名任务" : name;
    }

    private String basename(String path) {
        if (path == null || path.isEmpty()) return "";
        String normalized = path.replace('\\', '/');
        int idx = normalized.lastIndexOf('/');
        return idx >= 0 ? normalized.substring(idx + 1) : normalized;
    }

    private String backendLabel(String backend) {
        return backend != null && backend.toLowerCase().contains("claude") ? "Claude" : "Codex";
    }

    private String eventLabel(String kind) {
        if ("confirm".equals(kind)) return "需要确认";
        if ("plan".equals(kind)) return "计划待审阅";
        if ("done".equals(kind)) return "任务完成";
        return "Agent 通知";
    }

    private String eventHint(String kind) {
        if ("confirm".equals(kind)) return "点击处理确认请求";
        if ("plan".equals(kind)) return "点击审阅计划并决定是否继续";
        if ("done".equals(kind)) return "等待下一条指令";
        return "点击打开会话";
    }
}
