import 'dart:typed_data';

/// Smoothed input level for the VU meter, computed from raw PCM chunks.
///
/// Kept separate from the widget so the maths is testable without a
/// microphone: the meter was silently broken once by a RangeError thrown in
/// here, which also killed audio because it ran on the capture path.
class VuLevelTracker {
  VuLevelTracker({this.window = 50});

  /// How many chunks the moving average covers.
  final int window;

  final List<double> _recent = <double>[];
  double _level = 0.0;

  double get level => _level;

  void reset() {
    _recent.clear();
    _level = 0.0;
  }

  /// Feed one chunk of little-endian PCM16; returns the smoothed level (0..1).
  double add(Uint8List pcmChunk) {
    final int sampleCount = pcmChunk.length >> 1;
    if (sampleCount == 0) return _level;

    double sumSquares = 0.0;
    // ByteData reads are unaligned, unlike Int16List.view — the record
    // plugin's chunk can start at an odd offsetInBytes into its underlying
    // buffer, which made Int16List.view throw RangeError on every chunk.
    final ByteData samples = ByteData.sublistView(pcmChunk);
    for (int i = 0; i < sampleCount; i++) {
      final double normalized = samples.getInt16(i * 2, Endian.little) / 32768.0;
      sumSquares += normalized * normalized;
    }
    // Mean square rather than its root: keeps the meter's original
    // sensitivity, which was tuned against this curve.
    final double instant = (sumSquares / sampleCount).clamp(0.0, 1.0);

    _recent.add(instant);
    if (_recent.length > window) {
      _recent.removeAt(0);
    }
    double total = 0.0;
    for (final double value in _recent) {
      total += value;
    }
    _level = _recent.isEmpty ? 0.0 : total / _recent.length;
    return _level;
  }
}
