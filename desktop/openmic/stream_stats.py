"""Live quality metrics for the incoming audio stream.

The UI needs to answer "is this connection actually good?" — a VU meter
only proves audio is arriving, not that it arrives on time. These are the
three numbers that explain bad audio on WiFi: how much of the stream is
missing, how unevenly it arrives (jitter), and how much bandwidth it uses.
"""

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Optional

# RFC 3550's interarrival-jitter smoothing factor: each new deviation moves
# the estimate by 1/16th, so a single hiccup doesn't dominate the reading.
_JITTER_SMOOTHING = 16.0

DEFAULT_WINDOW_SECONDS = 2.0


@dataclass(frozen=True)
class StreamSnapshot:
    """Point-in-time view of stream quality. Safe to hand to the UI thread."""

    packets: int = 0
    lost: int = 0
    duplicates: int = 0
    reordered: int = 0
    loss_percent: float = 0.0
    jitter_ms: float = 0.0
    bitrate_kbps: float = 0.0
    buffer_ms: float = 0.0
    receiving: bool = False


class StreamStatsCollector:
    """Thread-safe packet accounting.

    ``record_packet`` runs on the asyncio loop thread (one packet per 20 ms);
    ``snapshot`` runs on the UI thread once a second.
    """

    def __init__(
        self,
        frame_ms: float = 20.0,
        window_seconds: float = DEFAULT_WINDOW_SECONDS,
    ):
        self._frame_ms = frame_ms
        self._window = window_seconds
        self._lock = threading.Lock()
        self._recent: deque[tuple[float, int]] = deque()  # (timestamp, size)
        self._packets = 0
        self._jitter_ms = 0.0
        self._last_arrival: Optional[float] = None

    def record_packet(self, size: int, now: Optional[float] = None) -> None:
        timestamp = time.monotonic() if now is None else now
        with self._lock:
            self._packets += 1
            self._recent.append((timestamp, size))
            self._trim(timestamp)
            if self._last_arrival is not None:
                # Deviation from the expected 20 ms spacing, smoothed.
                deviation = abs((timestamp - self._last_arrival) * 1000.0 - self._frame_ms)
                self._jitter_ms += (deviation - self._jitter_ms) / _JITTER_SMOOTHING
            self._last_arrival = timestamp

    def reset(self) -> None:
        with self._lock:
            self._recent.clear()
            self._packets = 0
            self._jitter_ms = 0.0
            self._last_arrival = None

    def snapshot(
        self,
        lost: int = 0,
        duplicates: int = 0,
        reordered: int = 0,
        loss_percent: float = 0.0,
        buffer_ms: float = 0.0,
        now: Optional[float] = None,
    ) -> StreamSnapshot:
        timestamp = time.monotonic() if now is None else now
        with self._lock:
            self._trim(timestamp)
            windowed_bytes = sum(size for _, size in self._recent)
            receiving = bool(self._recent)
            return StreamSnapshot(
                packets=self._packets,
                lost=lost,
                duplicates=duplicates,
                reordered=reordered,
                loss_percent=loss_percent,
                jitter_ms=self._jitter_ms,
                bitrate_kbps=windowed_bytes * 8 / 1000.0 / self._window,
                buffer_ms=buffer_ms,
                receiving=receiving,
            )

    def _trim(self, now: float) -> None:
        cutoff = now - self._window
        while self._recent and self._recent[0][0] < cutoff:
            self._recent.popleft()
