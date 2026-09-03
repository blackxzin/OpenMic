"""End-to-end codec test with the real libopus, no network and no PortAudio.

The unit tests stub the codec out, so this is the one place that proves the
actual decoder accepts our frames and that packet-loss concealment produces
real audio instead of a hole.
"""

import unittest

import numpy as np

from openmic import protocol
from openmic.opus_codec import OpusDecoder, OpusEncoder, _OPUS_AVAILABLE
from openmic.server import AudioBridge


def tone_frames(count: int) -> list[bytes]:
    """`count` frames of a 440 Hz sine at 48 kHz, PCM16 mono."""
    total = protocol.OPUS_FRAME_SAMPLES * count
    t = np.arange(total) / protocol.SAMPLE_RATE
    samples = (np.sin(2 * np.pi * 440 * t) * 12000).astype(np.int16)
    frame_bytes = protocol.OPUS_FRAME_SAMPLES * protocol.SAMPLE_WIDTH
    raw = samples.tobytes()
    return [raw[i : i + frame_bytes] for i in range(0, len(raw), frame_bytes)]


@unittest.skipUnless(_OPUS_AVAILABLE, "libopus not available")
class TestOpusRoundTrip(unittest.TestCase):
    def setUp(self):
        self.encoder = OpusEncoder()
        self.bridge = AudioBridge(sink_device_name="test")
        self.bridge.noise_suppression_enabled = False
        self.bridge._opus_decoder = OpusDecoder()

    def _drain(self) -> bytes:
        out = b""
        while not self.bridge._queue.empty():
            out += self.bridge._queue.get_nowait()
        return out

    def test_encoded_frames_decode_back_to_audio(self):
        for sequence, frame in enumerate(tone_frames(20)):
            self.bridge.push_opus(sequence, self.encoder.encode(frame))
        decoded = np.frombuffer(self._drain(), dtype=np.int16)
        self.assertGreater(len(decoded), 0)
        # Same signal level as went in, not silence or garbage.
        rms = float(np.sqrt(np.mean(decoded.astype(np.float64) ** 2)))
        self.assertGreater(rms, 1000.0)

    def test_concealed_frame_is_audio_not_silence(self):
        frames = tone_frames(20)
        for sequence, frame in enumerate(frames):
            if sequence == 10:
                continue  # this datagram "never arrived"
            self.bridge.push_opus(sequence, self.encoder.encode(frame))
        decoded = np.frombuffer(self._drain(), dtype=np.int16)
        self.assertEqual(self.bridge.stats().lost, 1)
        # Concealment extrapolates the tone; a flat gap would show up as a
        # run of zeros the length of a frame.
        longest_zero_run = 0
        current = 0
        for sample in decoded:
            current = current + 1 if sample == 0 else 0
            longest_zero_run = max(longest_zero_run, current)
        self.assertLess(longest_zero_run, protocol.OPUS_FRAME_SAMPLES)

    def test_bitrate_preset_changes_frame_size(self):
        frames = tone_frames(10)
        low = OpusEncoder(bitrate=protocol.OPUS_BITRATE_MIN)
        high = OpusEncoder(bitrate=protocol.OPUS_BITRATE_MAX)
        low_bytes = sum(len(low.encode(frame)) for frame in frames)
        high_bytes = sum(len(high.encode(frame)) for frame in frames)
        self.assertLess(low_bytes, high_bytes)


if __name__ == "__main__":
    unittest.main()
