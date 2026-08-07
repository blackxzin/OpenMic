import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';

import 'package:openmic_mobile/protocol.dart';

void main() {
  group('Protocol wiring parity with desktop', () {
    test('PAIR_RESP echoes the PIN as ASCII payload', () {
      final pin = '123456';
      final pkt = Protocol.packPairResponse(pin);
      expect(pkt[0], Protocol.pairResp);
      expect(pkt.sublist(1), utf8.encode(pin));
    });

    test('PAIR_RESP round-trips through desktop layout', () {
      // Must match desktop protocol.pack_pair_response("042513"):
      // [0x05] + "042513"
      expect(Protocol.packPairResponse('042513'), [0x05, 0x30, 0x34, 0x32, 0x35, 0x31, 0x33]);
    });

    test('HELLO/PAIR_CHAL/PAIR_ACK pack+unpack round-trip', () {
      final hello = Protocol.packHello('Pixel');
      final parsedHello = Protocol.unpack(hello);
      expect(parsedHello!['type'], Protocol.hello);
      expect(parsedHello['name'], 'Pixel');

      final chal = Uint8List.fromList([Protocol.pairChal, ...'998877'.codeUnits]);
      final parsed = Protocol.unpack(chal)!;
      expect(parsed['type'], Protocol.pairChal);
      expect(parsed['pin'], '998877');

      final ack = Uint8List.fromList([
        Protocol.pairAck,
        ...List.filled(16, 1),
        ...List.filled(16, 2),
      ]);
      final parsedAck = Protocol.unpack(ack)!;
      expect(parsedAck['type'], Protocol.pairAck);
      expect((parsedAck['deviceId'] as Uint8List).length, 16);
      expect((parsedAck['authToken'] as Uint8List).length, 16);
    });

    test('audio constants match desktop', () {
      expect(Protocol.sampleRate, 48000);
      expect(Protocol.channels, 1);
      expect(Protocol.opusFrameSamples, 960);
      expect(Protocol.deviceIdLen, 16);
      expect(Protocol.authTokenLen, 16);
      expect(Protocol.version, 0x01);
    });
  });
}