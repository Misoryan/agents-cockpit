package net.easecation.agentcockpit;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.drawable.Drawable;

final class NotificationLogo {
    static final int ACCENT_COLOR = 0xff0a84ff;

    private NotificationLogo() {
    }

    static Bitmap largeIcon(Context context) {
        if (context == null) return null;
        Drawable drawable = context.getDrawable(R.drawable.ic_launcher_agent);
        if (drawable == null) return null;
        int size = Math.max(64, Math.round(48 * context.getResources().getDisplayMetrics().density));
        Bitmap bitmap = Bitmap.createBitmap(size, size, Bitmap.Config.ARGB_8888);
        Canvas canvas = new Canvas(bitmap);
        drawable.setBounds(0, 0, canvas.getWidth(), canvas.getHeight());
        drawable.draw(canvas);
        return bitmap;
    }
}
