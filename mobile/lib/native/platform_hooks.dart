import 'dart:io';

import 'package:flutter/services.dart';

/// Android-only native helpers. See MainActivity.kt for what each side does.
const MethodChannel _nativeChannel = MethodChannel('dev.openmic/wifi_lock');

/// Keeps the WiFi radio at full power (WIFI_MODE_FULL_HIGH_PERF) while
/// connected/pairing — see MainActivity.kt for why this exists.
Future<void> acquireWifiLock() => _invoke('acquire');

Future<void> releaseWifiLock() => _invoke('release');

/// Runs a foreground service with a persistent notification while streaming.
/// Without this, Android is free to suspend mic capture in the background
/// (screen off, app not visible) with no error surfaced anywhere — audio
/// just silently stops, same failure class the WifiLock above fixes for the
/// network side. Mirrors the WifiLock's lifecycle: held through reconnect
/// attempts, released on dispose, give-up, or user-initiated disconnect.
Future<void> startForegroundService() => _invoke('startForegroundService');

Future<void> stopForegroundService() => _invoke('stopForegroundService');

Future<void> _invoke(String method) async {
  if (!Platform.isAndroid) return;
  try {
    await _nativeChannel.invokeMethod(method);
  } on PlatformException {
    // Best-effort: streaming still works without these, it's just more
    // exposed to the radio idling down or the OS suspending capture.
  } on MissingPluginException {
    // Same story when the native side isn't registered (e.g. tests).
  }
}
