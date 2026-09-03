import 'package:shared_preferences/shared_preferences.dart';

import '../protocol.dart';

/// User preferences that outlive a session. Not secret, unlike the pairing
/// credentials in CredentialsStore.
class SettingsStore {
  static const String _bitrateKey = 'opus_bitrate';

  Future<int> loadBitrate() async {
    final prefs = await SharedPreferences.getInstance();
    return Protocol.clampBitrate(prefs.getInt(_bitrateKey) ?? Protocol.opusBitrate);
  }

  Future<void> saveBitrate(int bitrate) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setInt(_bitrateKey, Protocol.clampBitrate(bitrate));
  }
}
