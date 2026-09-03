"""Opus codec wrapper for decoding Opus frames to PCM16 on the desktop side.

Uses pyopus (python-opus) which wraps libopus. Falls back gracefully if unavailable.
"""

import logging
from typing import Optional

from . import protocol
from .native_libs import library_fallback

_log = logging.getLogger(__name__)

try:
    # opuslib resolves libopus at import time and raises a bare Exception
    # when find_library comes back empty — catching only ImportError here
    # let that escape and killed the app at startup on any machine without
    # libopus installed.
    with library_fallback("opus"):
        import opuslib
        import opuslib.api.decoder
    _OPUS_AVAILABLE = True
except Exception as exc:  # noqa: BLE001 - see comment above
    _OPUS_AVAILABLE = False
    _log.warning("Opus unavailable (%s) — install libopus to decode Opus audio", exc)


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

    def decode_lost(self) -> Optional[bytes]:
        """Synthesize the frame that never arrived (packet-loss concealment).

        libopus reconstructs a plausible continuation of the last decoded
        frame when handed a NULL packet, which sounds far better than the
        alternatives: playing the *next* frame early (audible click plus a
        permanent timing shift) or inserting flat silence (a hard gap in the
        middle of a word). opuslib's high-level Decoder.decode() calls
        len(opus_data), so NULL has to go through the C wrapper directly.
        """
        if self._decoder is None:
            return None
        return opuslib.api.decoder.decode(
            self._decoder.decoder_state,
            None,
            0,
            protocol.OPUS_FRAME_SAMPLES,
            False,
            channels=protocol.CHANNELS,
        )


class OpusEncoder:
    """Encodes PCM16 to Opus frames on the mobile side (or for testing)."""

    def __init__(self, bitrate: int = protocol.OPUS_BITRATE):
        if not _OPUS_AVAILABLE:
            self._encoder = None
            return
        self._encoder = opuslib.Encoder(
            fs=protocol.SAMPLE_RATE,
            channels=protocol.CHANNELS,
            application="voip",
        )
        self._encoder.bitrate = protocol.clamp_bitrate(bitrate)

    @property
    def available(self) -> bool:
        return _OPUS_AVAILABLE

    def encode(self, pcm: bytes) -> Optional[bytes]:
        """Encode PCM16 bytes to an Opus frame. Returns None if unavailable."""
        if self._encoder is None:
            return None
        return self._encoder.encode(pcm, frame_size=protocol.OPUS_FRAME_SAMPLES)
