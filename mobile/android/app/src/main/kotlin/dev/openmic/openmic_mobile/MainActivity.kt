package dev.openmic.openmic_mobile

import android.content.Context
import android.net.wifi.WifiManager
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

/**
 * Holds a WifiManager.WifiLock (WIFI_MODE_FULL_HIGH_PERF) while streaming or
 * mid-pairing. Without it, the radio can drop to a power-save state during
 * an idle stretch (e.g. the user reading the pairing PIN dialog before
 * confirming) that leaves an already-open UDP socket unable to send —
 * RawDatagramSocket.send() then returns 0 instead of throwing, silently
 * dropping the packet, observed to persist well past any reasonable retry
 * window. The lock is the standard Android mechanism VoIP/streaming apps use
 * for exactly this class of problem.
 */
class MainActivity : FlutterActivity() {
    private val channelName = "dev.openmic/wifi_lock"
    private var wifiLock: WifiManager.WifiLock? = null

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

    override fun onDestroy() {
        releaseWifiLock()
        super.onDestroy()
    }
}
