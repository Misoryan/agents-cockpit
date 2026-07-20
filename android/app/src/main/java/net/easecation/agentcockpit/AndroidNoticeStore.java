package net.easecation.agentcockpit;

import android.content.Context;
import android.content.SharedPreferences;

final class AndroidNoticeStore {
    private static final String PREFS = "agent_android_state";
    private static final String PREFIX = "notice.";

    private AndroidNoticeStore() {
    }

    static void mark(Context context, String sid, String kind) {
        if (context == null) return;
        prefs(context).edit().putLong(key(sid, kind), System.currentTimeMillis()).apply();
    }

    static boolean recentlyNotified(Context context, String sid, String kind, long windowMs) {
        if (context == null) return false;
        long last = prefs(context).getLong(key(sid, kind), 0L);
        return last > 0 && System.currentTimeMillis() - last < windowMs;
    }

    private static SharedPreferences prefs(Context context) {
        return context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    private static String key(String sid, String kind) {
        return PREFIX + String.valueOf(sid == null ? "" : sid) + "." + String.valueOf(kind == null ? "" : kind);
    }
}
