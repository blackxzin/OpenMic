import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';

import 'package:openmic_mobile/storage/credentials_store.dart';

void main() {
  group('hex encoding', () {
    test('round-trips every byte value', () {
      final Uint8List bytes = Uint8List.fromList(List<int>.generate(256, (int i) => i));
      expect(hexToBytes(bytesToHex(bytes)), bytes);
    });

    test('pads single-digit bytes', () {
      expect(bytesToHex(<int>[0x00, 0x0f, 0xff]), '000fff');
    });

    test('malformed input returns null instead of throwing', () {
      // A corrupted keystore entry must re-trigger pairing, not crash the
      // app during startup.
      expect(hexToBytes('abc'), isNull);
      expect(hexToBytes('zz'), isNull);
      expect(hexToBytes(''), isNull);
    });
  });
}
