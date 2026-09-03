import 'package:flutter_test/flutter_test.dart';

import 'package:openmic_mobile/protocol.dart';
import 'package:openmic_mobile/ui/quality_selector.dart';

void main() {
  group('QualitySelector', () {
    test('a stored value snaps to an offered preset', () {
      // The dropdown asserts on a value that isn't one of its items.
      expect(Protocol.opusBitratePresets, contains(QualitySelector.snapToPreset(20000)));
      expect(QualitySelector.snapToPreset(24000), 24000);
      expect(QualitySelector.snapToPreset(12000), 16000);
      expect(QualitySelector.snapToPreset(64000), 48000);
    });

    test('every preset has its own label', () {
      final Set<String> labels =
          Protocol.opusBitratePresets.map(QualitySelector.labelFor).toSet();
      expect(labels.length, Protocol.opusBitratePresets.length);
    });
  });
}
