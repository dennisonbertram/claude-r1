package ai.r1.claude;

import android.app.Activity;
import android.content.BroadcastReceiver;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.database.ContentObserver;
import android.graphics.Color;
import android.hardware.Sensor;
import android.hardware.SensorEvent;
import android.hardware.SensorEventListener;
import android.hardware.SensorManager;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.VibrationEffect;
import android.os.Vibrator;
import android.provider.Settings;
import android.util.Log;
import android.view.KeyEvent;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.view.WindowManager;
import android.webkit.JavascriptInterface;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import java.net.HttpURLConnection;
import java.net.URL;

/**
 * Home-screen launcher for the R1: a full-screen WebView on the Termux voice server.
 * While the server is down it shows a built-in "Starting Claude…" page, probes the server
 * every 2s, and asks Termux to start it (at most once per 30s).
 * It is also the assistant (opened by holding the side button: start listening) and comes back
 * to the front whenever the screen turns on, so waking the R1 always lands in Claude.
 */
public class MainActivity extends Activity {
    private static final String TAG = "ClaudeR1";
    private static final String SERVER = "http://127.0.0.1:8765/";
    private static final String FALLBACK = "file:///android_asset/fallback.html";
    private static final long RETRY_MS = 2000;
    private static final long START_THROTTLE_MS = 30000;

    private final Handler handler = new Handler(Looper.getMainLooper());
    private WebView web;
    private boolean showingFallback;
    private boolean probing;
    private long lastStartAttempt;
    private volatile boolean awake;

    // ---- wireless debugging: Shizuku's no-root start switches it on and leaves it on; the voice server turns it
    // off again once Shizuku runs. Only apps can read the setting cheaply, so the launcher reports changes.
    private final ContentObserver adbWifi = new ContentObserver(new Handler(Looper.getMainLooper())) {
        @Override public void onChange(boolean selfChange) {
            reportAdbWifi();
        }
    };

    private void reportAdbWifi() {
        boolean on = Settings.Global.getInt(getContentResolver(), "adb_wifi_enabled", 0) == 1;
        new Thread(() -> post("api/adbwifi", "{\"on\":" + on + "}")).start();
    }

    // ---- motion: how the R1 is being held, for Claude's context (only while this screen is showing)
    private SensorManager sensors;
    private final float[] gravity = new float[3];
    private double motionSum, motionSq;
    private int motionN;
    private String lastPosture = "";
    private long lastPostureSent;

    private final SensorEventListener motion = new SensorEventListener() {
        @Override public void onSensorChanged(SensorEvent e) {
            if (e.sensor.getType() == Sensor.TYPE_GRAVITY) {
                System.arraycopy(e.values, 0, gravity, 0, 3);
            } else {                                    // linear acceleration: how much it's moving
                double m = Math.sqrt(e.values[0] * e.values[0] + e.values[1] * e.values[1] + e.values[2] * e.values[2]);
                motionSum += m;
                motionSq += m * m;
                motionN++;
            }
        }

        @Override public void onAccuracyChanged(Sensor s, int a) { }
    };

    private final Runnable reportMotion = new Runnable() {
        @Override public void run() {
            float x = gravity[0], y = gravity[1], z = gravity[2];
            String posture = z > 8 ? "lying face up" : z < -8 ? "lying face down"
                    : y > 6 ? "held upright, screen facing the user" : y < -6 ? "upside down"
                    : Math.abs(x) > 6 ? "on its side" : y > 3 ? "held tilted back" : "tilted";
            double mean = motionN > 0 ? motionSum / motionN : 0;
            double sd = motionN > 1 ? Math.sqrt(Math.max(0, motionSq / motionN - mean * mean)) : 0;
            String moving = mean < 0.3 ? "still" : mean > 1.2 || sd > 1.5 ? "moving a lot (walking or carried)"
                    : "slightly moving (in a hand)";
            motionSum = motionSq = 0;
            motionN = 0;
            String now = posture + ", " + moving;
            long t = System.currentTimeMillis();
            if (!now.equals(lastPosture) || t - lastPostureSent > 30000) {
                lastPosture = now;
                lastPostureSent = t;
                String body = String.format(java.util.Locale.US,
                        "{\"posture\":\"%s\",\"motion\":\"%s\",\"gravity\":[%.1f,%.1f,%.1f],\"movement\":%.2f}",
                        posture, moving, x, y, z, mean);
                new Thread(() -> post("api/sensors", body)).start();
            }
            handler.postDelayed(this, 2000);
        }
    };

    private final BroadcastReceiver screenOn = new BroadcastReceiver() {
        @Override public void onReceive(Context c, Intent i) {
            startActivity(new Intent(c, MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
            // waking can bring Android's navigation bar back without a focus change
            handler.postDelayed(MainActivity.this::hideSystemBars, 400);
            handler.postDelayed(MainActivity.this::hideSystemBars, 1500);
        }
    };

    private final Runnable probe = new Runnable() {
        @Override public void run() {
            if (!showingFallback) { probing = false; return; }
            startBackend();
            new Thread(() -> {
                boolean up = serverUp();
                handler.post(() -> {
                    if (!showingFallback) { probing = false; return; }
                    if (up) {
                        probing = false;
                        showingFallback = false;
                        web.loadUrl(SERVER);
                    } else {
                        handler.postDelayed(probe, RETRY_MS);
                    }
                });
            }).start();
        }
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().getDecorView().setBackgroundColor(Color.BLACK);

        web = new WebView(this);
        web.setBackgroundColor(Color.BLACK);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setAllowFileAccess(true);   // only for the bundled fallback page
        web.addJavascriptInterface(new Bridge(), "R1");
        web.setWebViewClient(new WebViewClient() {
            @Override
            public void onReceivedError(WebView view, WebResourceRequest req, WebResourceError err) {
                if (req.isForMainFrame()) showFallback();
            }

            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest req) {
                return false;
            }
        });
        setContentView(web);
        web.loadUrl(SERVER);
        registerReceiver(screenOn, new IntentFilter(Intent.ACTION_SCREEN_ON));
        sensors = getSystemService(SensorManager.class);
        getContentResolver().registerContentObserver(Settings.Global.getUriFor("adb_wifi_enabled"), false, adbWifi);
        handler.postDelayed(this::reportAdbWifi, 15000);   // at boot: once the voice server is likely up
        handleAssist(getIntent());
    }

    @Override
    protected void onDestroy() {
        unregisterReceiver(screenOn);
        getContentResolver().unregisterContentObserver(adbWifi);
        super.onDestroy();
    }

    /** Opened by a long press on the side button: tell the server to start listening. */
    private void handleAssist(Intent intent) {
        if (intent == null || !Intent.ACTION_ASSIST.equals(intent.getAction())) return;
        setIntent(new Intent());          // don't re-trigger on rotation or re-creation
        new Thread(() -> post("api/assist")).start();
    }

    private static void post(String path) {
        post(path, null);
    }

    private static void post(String path, String json) {
        HttpURLConnection c = null;
        try {
            c = (HttpURLConnection) new URL(SERVER + path).openConnection();
            c.setRequestMethod("POST");
            if (json != null) {
                c.setDoOutput(true);
                c.setRequestProperty("Content-Type", "application/json");
                c.getOutputStream().write(json.getBytes(java.nio.charset.StandardCharsets.UTF_8));
            }
            c.setConnectTimeout(1000);
            c.setReadTimeout(2000);
            c.getResponseCode();
        } catch (Exception e) {
            Log.w(TAG, "POST " + path + " failed", e);
        } finally {
            if (c != null) c.disconnect();
        }
    }

    @Override
    protected void onResume() {
        super.onResume();
        hideSystemBars();
        if (showingFallback) scheduleProbe(0);
        if (sensors != null) {
            for (int type : new int[]{Sensor.TYPE_GRAVITY, Sensor.TYPE_LINEAR_ACCELERATION}) {
                Sensor sn = sensors.getDefaultSensor(type);
                if (sn != null) sensors.registerListener(motion, sn, SensorManager.SENSOR_DELAY_UI);
            }
            handler.postDelayed(reportMotion, 1500);
        }
    }

    @Override
    protected void onPause() {
        super.onPause();
        if (sensors != null) sensors.unregisterListener(motion);
        handler.removeCallbacks(reportMotion);
    }

    @Override
    public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        if (hasFocus) hideSystemBars();
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        handleAssist(intent);
        // HOME pressed while we're already in front: just make sure we're showing something live
        if (showingFallback) scheduleProbe(0);
    }

    private void hideSystemBars() {
        WindowInsetsController c = getWindow().getInsetsController();
        if (c == null) return;
        c.hide(WindowInsets.Type.statusBars() | WindowInsets.Type.navigationBars());
        c.setSystemBarsBehavior(WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE);
    }

    private void showFallback() {
        if (!showingFallback) {
            showingFallback = true;
            web.loadUrl(FALLBACK);
        }
        scheduleProbe(RETRY_MS);
    }

    private void scheduleProbe(long delay) {
        if (probing) return;
        probing = true;
        handler.postDelayed(probe, delay);
    }

    private static boolean serverUp() {
        HttpURLConnection c = null;
        try {
            c = (HttpURLConnection) new URL(SERVER).openConnection();
            c.setConnectTimeout(1000);
            c.setReadTimeout(1500);
            return c.getResponseCode() < 500;
        } catch (Exception e) {
            return false;
        } finally {
            if (c != null) c.disconnect();
        }
    }

    /** Ask Termux to start the voice server. Needs allow-external-apps=true in termux.properties. */
    private void startBackend() {
        long now = System.currentTimeMillis();
        if (now - lastStartAttempt < START_THROTTLE_MS) return;
        lastStartAttempt = now;
        Intent i = new Intent("com.termux.RUN_COMMAND");
        i.setComponent(new ComponentName("com.termux", "com.termux.app.RunCommandService"));
        i.putExtra("com.termux.RUN_COMMAND_PATH", "/data/data/com.termux/files/usr/bin/voice-server");
        i.putExtra("com.termux.RUN_COMMAND_BACKGROUND", true);
        try {
            startService(i);
        } catch (Exception e) {
            Log.w(TAG, "could not start voice-server via Termux", e);
        }
    }

    @Override
    public boolean dispatchKeyEvent(KeyEvent event) {
        int code = event.getKeyCode();
        if (code == KeyEvent.KEYCODE_DPAD_UP || code == KeyEvent.KEYCODE_DPAD_DOWN) {
            // the scroll wheel: hand it to the page instead of moving WebView focus
            if (event.getAction() == KeyEvent.ACTION_DOWN) {
                String dir = code == KeyEvent.KEYCODE_DPAD_UP ? "up" : "down";
                web.evaluateJavascript("window.r1Key && r1Key('" + dir + "')", null);
            }
            return true;
        }
        return super.dispatchKeyEvent(event);
    }

    @Override
    public void onBackPressed() {
        // never leave the launcher
        if (web.canGoBack()) web.goBack();
    }

    /** Escape hatches into Android for the web UI: window.R1.openApp('com.foo') etc. */
    private class Bridge {
        @JavascriptInterface
        public boolean openApp(String pkg) {
            Intent i = getPackageManager().getLaunchIntentForPackage(pkg);
            if (i == null) return false;
            i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            runOnUiThread(() -> startActivity(i));
            return true;
        }

        @JavascriptInterface
        public void openSettings() {
            Intent i = new Intent(Settings.ACTION_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            runOnUiThread(() -> startActivity(i));
        }

        @JavascriptInterface
        public boolean openTermux() {
            return openApp("com.termux");
        }

        /** Keep the screen on only while Claude is listening, thinking or speaking. */
        @JavascriptInterface
        public void keepAwake(boolean on) {
            // called on every render: only touch the window when it changes, since a window
            // attribute change makes Android bring its navigation bar back
            if (on == awake) return;
            awake = on;
            runOnUiThread(() -> {
                if (on) getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
                else getWindow().clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
                hideSystemBars();
            });
        }

        /** "Tap to try again" on the starting page: ask Termux again right now. */
        @JavascriptInterface
        public void retryStart() {
            runOnUiThread(() -> {
                lastStartAttempt = 0;
                probing = false;
                handler.removeCallbacks(probe);
                scheduleProbe(0);
            });
        }

        /** The page lost its event stream: show "Starting Claude…" and bring the server back. */
        @JavascriptInterface
        public void serverDown() {
            runOnUiThread(MainActivity.this::showFallback);
        }

        @JavascriptInterface
        public void haptic() {
            Vibrator v = getSystemService(Vibrator.class);
            if (v != null && v.hasVibrator()) v.vibrate(VibrationEffect.createPredefined(VibrationEffect.EFFECT_CLICK));
        }
    }
}
