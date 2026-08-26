"""Tests for the spectral noise suppressor (no audio hardware needed)."""

import unittest

import numpy as np

from openmic.noise_suppression import NoiseSuppressor

_SAMPLE_RATE = 48000
_FRAME = 960


def _tone(freq: float, seconds: float, amplitude: float = 8000.0) -> np.ndarray:
    n = int(_SAMPLE_RATE * seconds)
    t = np.arange(n) / _SAMPLE_RATE
    return (np.sin(2 * np.pi * freq * t) * amplitude).astype(np.int16)


def _noise(seconds: float, amplitude: float = 300.0, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = int(_SAMPLE_RATE * seconds)
    return (rng.standard_normal(n) * amplitude).clip(-32768, 32767).astype(np.int16)


def _rms(samples: np.ndarray) -> float:
    return float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))


def _run(suppressor: NoiseSuppressor, samples: np.ndarray, chunk: int = _FRAME) -> np.ndarray:
    out = []
    for start in range(0, len(samples), chunk):
        piece = samples[start : start + chunk].tobytes()
        processed = suppressor.process(piece)
        if processed:
            out.append(np.frombuffer(processed, dtype=np.int16))
    return np.concatenate(out) if out else np.zeros(0, dtype=np.int16)


class TestNoiseSuppressor(unittest.TestCase):
    def test_disabled_is_passthrough(self):
        suppressor = NoiseSuppressor(frame_size=_FRAME)
        suppressor.enabled = False
        pcm = _tone(440, 0.02).tobytes()
        self.assertEqual(suppressor.process(pcm), pcm)

    def test_buffers_until_one_frame_is_available(self):
        suppressor = NoiseSuppressor(frame_size=_FRAME)
        half_frame = _tone(440, 0.02)[: _FRAME // 2].tobytes()
        self.assertEqual(suppressor.process(half_frame), b"")

    def test_attenuates_steady_noise_more_than_a_loud_tone(self):
        # Train the noise-floor estimate on background hiss alone, then feed
        # a loud tone on top of the same hiss. A working suppressor should
        # attenuate hiss-only stretches far more than voice-level content.
        suppressor = NoiseSuppressor(frame_size=_FRAME)
        noise_only = _noise(1.0, amplitude=300.0)
        _run(suppressor, noise_only)  # let the noise-floor estimate settle

        probe_noise = _noise(0.5, amplitude=300.0, seed=1)
        probe_tone = _tone(440, 0.5, amplitude=8000.0)

        out_noise = _run(suppressor, probe_noise)
        out_tone = _run(suppressor, probe_tone)

        self.assertGreater(len(out_noise), 0)
        self.assertGreater(len(out_tone), 0)
        noise_reduction_db = 20 * np.log10(_rms(probe_noise) / max(_rms(out_noise), 1e-6))
        tone_reduction_db = 20 * np.log10(_rms(probe_tone) / max(_rms(out_tone), 1e-6))

        self.assertGreater(noise_reduction_db, 6.0)  # hiss cut by at least ~2x
        self.assertLess(tone_reduction_db, noise_reduction_db)

    def test_reset_clears_learned_noise_floor_and_buffers(self):
        suppressor = NoiseSuppressor(frame_size=_FRAME)
        _run(suppressor, _noise(1.0, amplitude=300.0))
        self.assertIsNotNone(suppressor._noise_floor)

        suppressor.reset()

        self.assertIsNone(suppressor._noise_floor)
        self.assertEqual(len(suppressor._input), 0)
        self.assertTrue(np.all(suppressor._ola == 0))

    def test_output_stays_within_int16_range(self):
        suppressor = NoiseSuppressor(frame_size=_FRAME)
        loud = _tone(440, 0.5, amplitude=32000.0)
        out = _run(suppressor, loud)
        self.assertGreater(len(out), 0)
        self.assertTrue(np.all(out >= -32768))
        self.assertTrue(np.all(out <= 32767))


if __name__ == "__main__":
    unittest.main()
