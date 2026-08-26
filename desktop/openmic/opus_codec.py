"""Opus codec wrapper for decoding Opus frames to PCM16 on the desktop side.

Uses pyopus (python-opus) which wraps libopus. Falls back gracefully if unavailable.
"""

import logging
from typing import Optional

from . import protocol

_log = logging.getLogger(__name__)

try:
    import opuslib
    _OPUS_AVAILABLE = True
except ImportError:
    _OPUS_AVAILABLE = False
    _log.warning("opuslib not installed — Opus decoding disabled, falling back to PCM")


class OpusDecoder:
    """Decodes Opus frames back to PCM16 samples for playback."""

    def __init__(self):
        if not _OPUS_AVAILABLE:
            self._decoder = None
            return
        self._decoder = opuslib.Decoder(
            fs=protocol.SAMPLE_RATE,
            channels=protocol.CHANNELS,
        )

    @property
    def available(self) -> bool:
        return _OPUS_AVAILABLE

    def decode(self, opus_data: bytes) -> Optional[bytes]:
        """Decode an Opus frame to PCM16 bytes. Returns None if unavailable."""
        if self._decoder is None:
            return None
        pcm = self._decoder.decode(
            opus_data,
            frame_size=protocol.OPUS_FRAME_SAMPLES,
        )
        return pcm


class OpusEncoder:
    """Encodes PCM16 to Opus frames on the mobile side (or for testing)."""

    def __init__(self):
        if not _OPUS_AVAILABLE:
            self._encoder = None
            return
        self._encoder = opuslib.Encoder(
            fs=protocol.SAMPLE_RATE,
            channels=protocol.CHANNELS,
            application="voip",
        )
        self._encoder.bitrate = protocol.OPUS_BITRATE

    @property
    def available(self) -> bool:
        return _OPUS_AVAILABLE

    def encode(self, pcm: bytes) -> Optional[bytes]:
        """Encode PCM16 bytes to an Opus frame. Returns None if unavailable."""
        if self._encoder is None:
            return None
        return self._encoder.encode(pcm, frame_size=protocol.OPUS_FRAME_SAMPLES)
