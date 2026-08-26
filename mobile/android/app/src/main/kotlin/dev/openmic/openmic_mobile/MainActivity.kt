package dev.openmic.openmic_mobile

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.wifi.WifiManager
import android.os.Build
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

/**
 * Native helpers for two problems Android causes for a background audio
 * streamer that Flutter/Dart can't solve on its own:
 *
 * - WifiManager.WifiLock (WIFI_MODE_FULL_HIGH_PERF), held while streaming or
 *   mid-pairing. Without it, the radio can drop to a power-save state during
 *   an idle stretch (e.g. the user reading the pairing PIN dialog before
 *   confirming) that leaves an already-open UDP socket unable to send —
 *   RawDatagramSocket.send() then returns 0 instead of throwing, silently
 *   dropping the packet, observed to persist well past any reasonable retry
 *   window. The lock is the standard Android mechanism VoIP/streaming apps
 *   use for exactly this class of problem.
 * - A foreground service with a persistent notification, running for the
 *   same "while streaming" window. Without it, Android is free to suspend
 *   mic capture once the app is backgrounded (screen off, app switched
 *   away) — recording just silently stops with no exception anywhere.
 */
class MainActivity : FlutterActivity() {
    private val channelName = "dev.openmic/wifi_lock"
    private var wifiLock: WifiManager.WifiLock? = null

    override fun onCreate(savedInstanceState: android.os.Bundle?) {
        super.onCreate(savedInstanceState)
        // Notifications need runtime consent on API 33+. Fire-and-forget: if
        // denied, the foreground service still runs, its notification just
        // won't be visible (see StreamingForegroundService).
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) !=
            PackageManager.PERMISSION_GRANTED
        ) {
            ActivityCompat.requestPermissions(this, arrayOf(Manifest.permission.POST_NOTIFICATIONS), 1001)
        }
    }

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, channelName).setMethodCallHandler { call, result ->
            when (call.method) {
                "acquire" -> {
                    acquireWifiLock()
                    result.success(null)
                }
                "release" -> {
                    releaseWifiLock()
                    result.success(null)
                }
                "startForegroundService" -> {
                    startStreamingForegroundService()
                    result.success(null)
                }
                "stopForegroundService" -> {
                    stopStreamingForegroundService()
                    result.success(null)
                }
                else -> result.notImplemented()
            }
        }
    }

    private fun acquireWifiLock() {
        if (wifiLock?.isHeld == true) return
        val wifiManager = applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
        @Suppress("DEPRECATION")
        val lock = wifiManager.createWifiLock(WifiManager.WIFI_MODE_FULL_HIGH_PERF, "OpenMic:streaming")
        lock.setReferenceCounted(false)
        lock.acquire()
        wifiLock = lock
    }

    private fun releaseWifiLock() {
        wifiLock?.let { if (it.isHeld) it.release() }
        wifiLock = null
    }

    private fun startStreamingForegroundService() {
        val intent = Intent(this, StreamingForegroundService::class.java)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(intent)
        } else {
            startService(intent)
        }
    }

    private fun stopStreamingForegroundService() {
        stopService(Intent(this, StreamingForegroundService::class.java))
    }

    override fun onDestroy() {
        releaseWifiLock()
        stopStreamingForegroundService()
        super.onDestroy()
    }
}
