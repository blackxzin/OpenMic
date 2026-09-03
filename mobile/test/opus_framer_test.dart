import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';

import 'package:openmic_mobile/audio/opus_framer.dart';
import 'package:openmic_mobile/protocol.dart';

void main() {
  group('OpusFramer', () {
    final List<int> encodedSizes = <int>[];
    List<int> fakeEncode(Int16List frame) {
      encodedSizes.add(frame.length);
      return <int>[0xAA, frame.length & 0xFF];
    }

    setUp(encodedSizes.clear);

    test('a partial chunk produces no frame and stays buffered', () {
      final OpusFramer framer = OpusFramer();
      final List<Uint8List> frames = framer.addChunk(Uint8List(100), fakeEncode);
      expect(frames, isEmpty);
      expect(framer.pendingBytes, 100);
    });

    test('every frame handed to the encoder has the exact sample count', () {
      final OpusFramer framer = OpusFramer();
      // Two and a half frames' worth of audio, delivered as one chunk.
      final int frameBytes = Protocol.opusFrameSamples * 2;
      framer.addChunk(Uint8List((frameBytes * 2.5).round()), fakeEncode);
      expect(encodedSizes, <int>[Protocol.opusFrameSamples, Protocol.opusFrameSamples]);
      expect(framer.pendingBytes, frameBytes ~/ 2);
    });

    test('samples split across chunks are not lost', () {
      final OpusFramer framer = OpusFramer();
      final int frameBytes = Protocol.opusFrameSamples * 2;
      framer.addChunk(Uint8List(frameBytes - 2), fakeEncode);
      final List<Uint8List> frames = framer.addChunk(Uint8List(2), fakeEncode);
      expect(frames.length, 1);
      expect(framer.pendingBytes, 0);
    });

    test('little-endian sample pairs are decoded, not raw bytes', () {
      final OpusFramer framer = OpusFramer(frameSamples: 2);
      Int16List? seen;
      framer.addChunk(Uint8List.fromList(<int>[0x00, 0x01, 0xFF, 0x7F]), (Int16List frame) {
        seen = Int16List.fromList(frame);
        return <int>[1];
      });
      expect(seen, isNotNull);
      expect(seen![0], 0x0100);
      expect(seen![1], 0x7FFF);
    });

    test('an empty encoder result is not sent as a frame', () {
      final OpusFramer framer = OpusFramer(frameSamples: 2);
      final List<Uint8List> frames =
          framer.addChunk(Uint8List(4), (Int16List frame) => <int>[]);
      expect(frames, isEmpty);
    });

    test('clear drops buffered samples', () {
      final OpusFramer framer = OpusFramer();
      framer.addChunk(Uint8List(100), fakeEncode);
      framer.clear();
      expect(framer.pendingBytes, 0);
    });
  });

  group('Bitrate presets', () {
    test('a 20 ms frame at 24 kbps caps at 60 bytes', () {
      expect(Protocol.maxFrameBytesFor(24000), 60);
    });

    test('presets are ordered and inside the supported range', () {
      for (final int preset in Protocol.opusBitratePresets) {
        expect(preset, greaterThanOrEqualTo(Protocol.opusBitrateMin));
        expect(preset, lessThanOrEqualTo(Protocol.opusBitrateMax));
        expect(Protocol.clampBitrate(preset), preset);
      }
    });

    test('out-of-range values clamp', () {
      expect(Protocol.clampBitrate(1000), Protocol.opusBitrateMin);
      expect(Protocol.clampBitrate(500000), Protocol.opusBitrateMax);
    });
  });
}
