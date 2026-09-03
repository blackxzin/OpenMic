import 'dart:typed_data';

import '../protocol.dart';

/// Encodes exactly one Opus frame worth of samples. Injected so the framing
/// logic can be tested without libopus loaded.
typedef FrameEncoder = List<int> Function(Int16List frame);

/// Turns the recorder's arbitrarily-sized PCM chunks into whole Opus frames.
///
/// libopus only accepts an exact sample count per call
/// ([Protocol.opusFrameSamples]), and the recorder yields whatever size the
/// platform feels like — feeding those straight in truncated most of every
/// frame, which is what made early builds sound like static.
class OpusFramer {
  OpusFramer({this.frameSamples = Protocol.opusFrameSamples});

  final int frameSamples;
  final List<int> _pcm = <int>[];

  /// Samples buffered but not yet part of a whole frame.
  int get pendingBytes => _pcm.length;

  void clear() => _pcm.clear();

  /// Accumulate [pcmChunk] and return every complete frame it produced.
  List<Uint8List> addChunk(Uint8List pcmChunk, FrameEncoder encode) {
    final int frameBytes = frameSamples * 2;
    final List<Uint8List> frames = <Uint8List>[];
    _pcm.addAll(pcmChunk);
    while (_pcm.length >= frameBytes) {
      // Decode little-endian byte pairs into int16 samples (matches the
      // desktop's np.frombuffer(dtype=int16) reader) — Int16List.fromList
      // would instead treat each raw byte as a whole sample.
      final Uint8List rawFrame = Uint8List.fromList(_pcm.sublist(0, frameBytes));
      final Int16List samples = Int16List.view(rawFrame.buffer, 0, frameSamples);
      _pcm.removeRange(0, frameBytes);
      final List<int> encoded = encode(samples);
      if (encoded.isNotEmpty) {
        frames.add(Uint8List.fromList(encoded));
      }
    }
    return frames;
  }
}
