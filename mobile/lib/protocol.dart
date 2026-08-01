import 'dart:convert';
import 'dart:typed_data';

/// Wire protocol shared with the desktop app. See desktop/openmic/protocol.py
/// and docs/protocol.md for the full spec.
class Protocol {
  static const int hello = 0x01;
  static const int audio = 0x02;
  static const int bye = 0x03;

  static const int sampleRate = 48000;
  static const int channels = 1;

  static Uint8List packHello(String deviceName) {
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

  static Uint8List packBye() {
    return Uint8List.fromList([bye]);
  }
}
