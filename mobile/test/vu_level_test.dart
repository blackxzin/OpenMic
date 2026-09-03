import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';

import 'package:openmic_mobile/audio/vu_level.dart';

/// Little-endian PCM16 chunk where every sample has the same amplitude.
Uint8List pcmChunk(int amplitude, int sampleCount) {
  final Uint8List bytes = Uint8List(sampleCount * 2);
  final ByteData view = ByteData.sublistView(bytes);
  for (int i = 0; i < sampleCount; i++) {
    view.setInt16(i * 2, amplitude, Endian.little);
  }
  return bytes;
}

void main() {
  group('VuLevelTracker', () {
    test('silence reads zero', () {
      final VuLevelTracker tracker = VuLevelTracker();
      expect(tracker.add(pcmChunk(0, 100)), 0.0);
    });

    test('louder audio reads higher', () {
      final double quiet = VuLevelTracker().add(pcmChunk(1000, 100));
      final double loud = VuLevelTracker().add(pcmChunk(20000, 100));
      expect(loud, greaterThan(quiet));
      expect(loud, lessThanOrEqualTo(1.0));
    });

    test('an empty chunk keeps the previous level', () {
      final VuLevelTracker tracker = VuLevelTracker();
      final double level = tracker.add(pcmChunk(20000, 100));
      expect(tracker.add(Uint8List(0)), level);
    });

    test('an odd-length chunk does not throw', () {
      // The recorder can hand over a buffer at an odd offset/length; this
      // used to raise RangeError and silently kill the capture stream.
      final VuLevelTracker tracker = VuLevelTracker();
      expect(() => tracker.add(Uint8List.fromList(<int>[1, 2, 3])), returnsNormally);
    });

    test('the moving average smooths a single loud chunk', () {
      final VuLevelTracker tracker = VuLevelTracker(window: 10);
      for (int i = 0; i < 9; i++) {
        tracker.add(pcmChunk(0, 100));
      }
      final double smoothed = tracker.add(pcmChunk(32000, 100));
      final double instant = VuLevelTracker(window: 1).add(pcmChunk(32000, 100));
      expect(smoothed, lessThan(instant));
    });

    test('reset returns to zero', () {
      final VuLevelTracker tracker = VuLevelTracker();
      tracker.add(pcmChunk(20000, 100));
      tracker.reset();
      expect(tracker.level, 0.0);
    });
  });
}
