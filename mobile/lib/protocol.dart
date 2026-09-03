import 'dart:convert';
import 'dart:typed_data';

/// Wire protocol shared with the desktop app. See desktop/openmic/protocol.py
/// and docs/protocol.md for the full spec.
class Protocol {
  static const int hello = 0x01;
  static const int audio = 0x02;        // raw PCM16 (legacy)
  static const int bye = 0x03;
  static const int pairChal = 0x04;
  static const int pairResp = 0x05;
  static const int pairAck = 0x06;
  static const int audioOpus = 0x07;    // Opus-encoded audio frame

  static const int version = 0x01;

  static const int sampleRate = 48000;
  static const int channels = 1;

  // Opus settings (must match desktop)
  static const int opusBitrate = 24000;
  static const int opusFrameSizeMs = 20;
  static const int opusFrameSamples = 960;  // 48000 * 20 / 1000

  // Selectable quality presets. Only the encoder needs to know the bitrate:
  // an Opus frame carries its own configuration, so the desktop decodes any
  // of these without being told which one is in use.
  static const int opusBitrateMin = 12000;
  static const int opusBitrateMax = 64000;
  static const List<int> opusBitratePresets = <int>[16000, 24000, 48000];

  /// Keep a requested bitrate inside the range libopus handles for voice.
  static int clampBitrate(int value) {
    if (value < opusBitrateMin) return opusBitrateMin;
    if (value > opusBitrateMax) return opusBitrateMax;
    return value;
  }

  /// Output-buffer size that caps one frame at [bitrate].
  ///
  /// opus_dart 3.x exposes no OPUS_SET_BITRATE control, but libopus treats
  /// the output buffer it is handed as a hard ceiling for that frame and
  /// lowers quality to fit — so sizing the buffer per frame is how the
  /// quality presets are actually enforced. It is a ceiling, not a target:
  /// quiet audio still encodes smaller.
  static int maxFrameBytesFor(int bitrate) {
    final framesPerSecond = 1000 ~/ opusFrameSizeMs;
    return clampBitrate(bitrate) ~/ 8 ~/ framesPerSecond;
  }

  static const int deviceIdLen = 16;
  static const int authTokenLen = 16;
  static const int pinLen = 6;

  static Uint8List packHello(String deviceName) {
    final nameBytes = utf8.encode(deviceName);
    final packet = Uint8List(2 + nameBytes.length);
    packet[0] = hello;
    packet[1] = version;
    packet.setRange(2, packet.length, nameBytes);
    return packet;
  }

  static Uint8List packHelloPaired(List<int> deviceId, List<int> authToken, String deviceName) {
    final nameBytes = utf8.encode(deviceName);
    final packet = Uint8List(2 + deviceIdLen + authTokenLen + nameBytes.length);
    packet[0] = hello;
    packet[1] = version;
    packet.setRange(2, 2 + deviceIdLen, deviceId);
    packet.setRange(2 + deviceIdLen, 2 + deviceIdLen + authTokenLen, authToken);
    packet.setRange(2 + deviceIdLen + authTokenLen, packet.length, nameBytes);
    return packet;
  }

  /// Pack a pre-versioning HELLO for pairing challenge (no version byte).
  static Uint8List packHelloV0(String deviceName) {
    final nameBytes = utf8.encode(deviceName);
    final packet = Uint8List(1 + nameBytes.length);
    packet[0] = hello;
    packet.setRange(1, packet.length, nameBytes);
    return packet;
  }

  static Uint8List packAudio(int sequence, Uint8List pcm) {
    final packet = Uint8List(5 + pcm.length);
    packet[0] = audio;
    packet.buffer.asByteData().setUint32(1, sequence, Endian.big);
    packet.setRange(5, packet.length, pcm);
    return packet;
  }

  static Uint8List packAudioOpus(int sequence, Uint8List opusData) {
    final packet = Uint8List(5 + opusData.length);
    packet[0] = audioOpus;
    packet.buffer.asByteData().setUint32(1, sequence, Endian.big);
    packet.setRange(5, packet.length, opusData);
    return packet;
  }

  static Uint8List packBye() {
    return Uint8List.fromList([bye]);
  }

  static Uint8List packPairResponse(String pin) {
    final bytes = utf8.encode(pin);
    final packet = Uint8List(1 + bytes.length);
    packet[0] = pairResp;
    packet.setRange(1, packet.length, bytes);
    return packet;
  }

  /// Returns (packetType, payload) or null if invalid.
  /// Payload varies by type:
  /// - HELLO: {version: int, deviceId: Uint8List?, authToken: Uint8List?, name: String}
  /// - PAIR_CHAL: String (PIN)
  /// - PAIR_ACK: {deviceId: Uint8List, authToken: Uint8List}
  /// - AUDIO: (sequence, pcm) — not parsed here, handled directly
  /// - PAIR_RESP, BYE: null
  static dynamic unpack(Uint8List packet) {
    if (packet.isEmpty) return null;
    final type = packet[0];
    switch (type) {
      case hello:
        // v1 protocol uses PROTOCOL_VERSION byte; v0 (pre-versioning) has name at packet[1].
        if (packet.length < 3) return null;
        final version = packet[1];
        if (version == Protocol.version) {
          // Check if paired HELLO (has device_id + auth_token = 32 bytes before name)
          if (packet.length >= 2 + deviceIdLen + authTokenLen) {
            final deviceId = packet.sublist(2, 2 + deviceIdLen);
            final authToken = packet.sublist(2 + deviceIdLen, 2 + deviceIdLen + authTokenLen);
            final name = utf8.decode(packet.sublist(2 + deviceIdLen + authTokenLen));
            return {
              'type': hello,
              'version': version,
              'deviceId': deviceId,
              'authToken': authToken,
              'name': name,
            };
          }
          // Regular v1 HELLO
          return {
            'type': hello,
            'version': version,
            'deviceId': null,
            'authToken': null,
            'name': utf8.decode(packet.sublist(2)),
          };
        }
        // Backward compat: treat as pre-versioning HELLO
        return {
          'type': hello,
          'version': 0,
          'deviceId': null,
          'authToken': null,
          'name': utf8.decode(packet.sublist(1)),
        };
      case pairChal:
        if (packet.length < 1 + pinLen) return null;
        return {
          'type': pairChal,
          'pin': utf8.decode(packet.sublist(1, 1 + pinLen)),
        };
      case pairAck:
        if (packet.length < 1 + deviceIdLen + authTokenLen) return null;
        return {
          'type': pairAck,
          'deviceId': packet.sublist(1, 1 + deviceIdLen),
          'authToken': packet.sublist(1 + deviceIdLen, 1 + deviceIdLen + authTokenLen),
        };
      case bye:
        return {'type': bye};
      default:
        return null;
    }
  }
}
