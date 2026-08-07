"""Funcional tests for the Opus codec layer (skips gracefully if opuslib is
not installed). Opus is lossy, so we assert frame length and RMS energy rather
than byte equality."""

import array
import unittest

import numpy as np

from openmic import protocol as p
from openmic.opus_codec import OpusDecoder, OpusEncoder, _OPUS_AVAILABLE


@unittest.skipUnless(_OPUS_AVAILABLE, "opuslib not installed")
class TestOpusRoundTrip(unittest.TestCase):
    def test_roundtrip_length_and_energy(self):
        n = p.OPUS_FRAME_SAMPLES
        t = np.arange(n) / p.SAMPLE_RATE
        pcm = (np.sin(2 * np.pi * 440 * t) * 1000).astype(np.int16).tobytes()

        enc = OpusEncoder()
        dec = OpusDecoder()
        opus = enc.encode(pcm)
        self.assertIsNotNone(opus)

        pcm_out = dec.decode(opus)
        self.assertIsNotNone(pcm_out)
        self.assertEqual(len(pcm_out), len(pcm))  # back to 960 int16 samples

        in_rms = np.sqrt(np.mean(np.frombuffer(pcm, np.int16).astype(float) ** 2))
        out_rms = np.sqrt(np.mean(np.frombuffer(pcm_out, np.int16).astype(float) ** 2))
        # Decoder preserves energy within a couple dB of the source.
        self.assertGreater(out_rms, in_rms * 0.5)
        self.assertLess(out_rms, in_rms * 2.0)

    def test_frame_and_packet_sizes(self):
        n = p.OPUS_FRAME_SAMPLES
        self.assertEqual(n, 960)
        self.assertEqual(n * 2, 1920)  # bytes per intra16 frame


if __name__ == "__main__":
    unittest.main()