import 'dart:typed_data';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Credentials handed out by the desktop when a device is paired.
class DeviceCredentials {
  const DeviceCredentials({required this.deviceId, required this.authToken});

  final Uint8List deviceId;
  final Uint8List authToken;
}

/// Hex-encodes bytes for storage (2 chars per byte).
String bytesToHex(List<int> bytes) =>
    bytes.map((b) => b.toRadixString(16).padLeft(2, '0')).join();

/// Inverse of [bytesToHex]. Returns null when the string isn't valid hex,
/// so a corrupted keystore entry re-triggers pairing instead of throwing
/// during startup.
Uint8List? hexToBytes(String hex) {
  if (hex.isEmpty || hex.length.isOdd) return null;
  final out = Uint8List(hex.length ~/ 2);
  for (int i = 0; i < out.length; i++) {
    final byte = int.tryParse(hex.substring(i * 2, i * 2 + 2), radix: 16);
    if (byte == null) return null;
    out[i] = byte;
  }
  return out;
}

/// Persists the pairing credentials in the platform keystore/keychain.
class CredentialsStore {
  const CredentialsStore({FlutterSecureStorage storage = const FlutterSecureStorage()})
      : _storage = storage;

  final FlutterSecureStorage _storage;

  static const String _deviceIdKey = 'device_id';
  static const String _authTokenKey = 'auth_token';

  Future<DeviceCredentials?> load() async {
    final deviceIdHex = await _storage.read(key: _deviceIdKey);
    final authTokenHex = await _storage.read(key: _authTokenKey);
    if (deviceIdHex == null || authTokenHex == null) return null;
    final deviceId = hexToBytes(deviceIdHex);
    final authToken = hexToBytes(authTokenHex);
    if (deviceId == null || authToken == null) return null;
    return DeviceCredentials(deviceId: deviceId, authToken: authToken);
  }

  Future<void> save(DeviceCredentials credentials) async {
    await _storage.write(key: _deviceIdKey, value: bytesToHex(credentials.deviceId));
    await _storage.write(key: _authTokenKey, value: bytesToHex(credentials.authToken));
  }

  Future<void> clear() async {
    await _storage.delete(key: _deviceIdKey);
    await _storage.delete(key: _authTokenKey);
  }
}
