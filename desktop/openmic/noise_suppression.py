"""Real-time spectral noise suppression for the received PCM stream.

Runs a Wiener-style gain filter over each analysis frame: frequency bins near
the tracked noise floor are attenuated, bins clearly above it (voice) pass
through mostly untouched. Frames are processed with weighted overlap-add
(WOLA) using a Hann analysis window, so the gain changing frame to frame
doesn't produce audible clicks — Hann's 50%-overlap sum equals a constant, so
adding back the unwindowed synthesis frames reconstructs the signal cleanly.
"""

from typing import Optional

import numpy as np

# How fast the noise-floor estimate reacts. The floor should drop quickly
# when the room actually goes quiet, but rise slowly so a burst of speech
# isn't mistaken for a rising noise floor.
_NOISE_RISE = 0.98
_NOISE_FALL = 0.90

# Bins are floored to a small residual gain rather than driven to zero —
# hard-muting would make silence between words flip 0/1 across neighbouring
# bins frame to frame, audible as "musical noise".
_GAIN_FLOOR = 0.05


class NoiseSuppressor:
    """Frame-by-frame spectral noise gate over a mono int16 PCM stream."""

    def __init__(self, frame_size: int = 960):
        self._frame_size = frame_size
        self._hop = frame_size // 2
        self._window = np.hanning(frame_size).astype(np.float32)
        self._input = np.zeros(0, dtype=np.float32)
        self._ola = np.zeros(frame_size, dtype=np.float32)
        self._noise_floor: Optional[np.ndarray] = None
        self.enabled = True
        # 0.0 = bypass gain math (still runs through OLA), 1.0 = full
        # subtraction of the tracked noise floor.
        self.strength = 1.0

    def reset(self) -> None:
        """Drop all buffered samples and the learned noise floor.

        Call between sessions (server stop/start) so noise learned from a
        previous connection doesn't bias the start of the next one.
        """
        self._input = np.zeros(0, dtype=np.float32)
        self._ola = np.zeros(self._frame_size, dtype=np.float32)
        self._noise_floor = None

    def process(self, pcm: bytes) -> bytes:
        """Feed in PCM16 bytes; returns the processed bytes ready so far.

        Because frames are analysed with 50% overlap, output lags input by
        half a frame — a chunk may return fewer processed bytes than were
        fed in (or none yet, while the first frame fills). Nothing is lost:
        unprocessed samples stay buffered for the next call.
        """
        if not self.enabled:
            return pcm

        incoming = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
        self._input = np.concatenate([self._input, incoming])

        out_frames = []
        while len(self._input) >= self._frame_size:
            frame = self._input[: self._frame_size]
            self._input = self._input[self._hop :]

            self._ola[: self._frame_size] += self._process_frame(frame)
            out_frames.append(self._ola[: self._hop].copy())
            self._ola = np.concatenate(
                [self._ola[self._hop :], np.zeros(self._hop, dtype=np.float32)]
            )

        if not out_frames:
            return b""
        out = np.concatenate(out_frames)
        return out.clip(-32768, 32767).astype(np.int16).tobytes()

    def _process_frame(self, frame: np.ndarray) -> np.ndarray:
        spectrum = np.fft.rfft(frame * self._window)
        magnitude = np.abs(spectrum)

        if self._noise_floor is None:
            self._noise_floor = magnitude.copy()
        else:
            rising = magnitude > self._noise_floor
            self._noise_floor = np.where(
                rising,
                self._noise_floor * _NOISE_RISE + magnitude * (1.0 - _NOISE_RISE),
                self._noise_floor * _NOISE_FALL + magnitude * (1.0 - _NOISE_FALL),
            )

        ratio = self._noise_floor / np.maximum(magnitude, 1e-6)
        gain = np.clip(1.0 - self.strength * ratio, _GAIN_FLOOR, 1.0)
        return np.fft.irfft(spectrum * gain, n=self._frame_size).astype(np.float32)
