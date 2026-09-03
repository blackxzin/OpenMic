"""Reorder, dedupe and gap-detect the UDP audio stream before decoding.

The phone sends one datagram per 20 ms audio frame, each stamped with a
32-bit sequence number. UDP gives no ordering and no delivery guarantee, so
handing packets straight to the decoder in arrival order plays reordered
frames backwards, plays duplicates twice, and hides losses (the next frame
just plays early, which sounds like a click). This buffer holds a couple of
frames back so late arrivals still land in their own slot, and reports a
missing frame as an explicit ``None`` so the caller can run packet-loss
concealment instead.

Depth is a latency/robustness trade: every held frame is 20 ms of added
delay. Three frames (60 ms) absorbs typical home-WiFi reordering without
being audible as lag.
"""

from dataclasses import dataclass, replace
from typing import Optional

SEQ_SPACE = 1 << 32
_HALF_SPACE = SEQ_SPACE // 2

DEFAULT_DEPTH = 3
# A jump bigger than this is a new stream (phone reconnected and restarted
# its counter), not a burst of loss — concealing it frame by frame would
# stall audio for as long as the gap.
DEFAULT_MAX_GAP = 100


def seq_diff(a: int, b: int) -> int:
    """Signed distance from ``b`` to ``a`` on the 32-bit sequence circle.

    Plain subtraction breaks at wraparound: sequence 0 arriving right after
    0xFFFFFFFF is the *next* frame, not four billion frames late.
    """
    return ((a - b + _HALF_SPACE) % SEQ_SPACE) - _HALF_SPACE


@dataclass(frozen=True)
class JitterStats:
    """Counters for what the buffer did with the stream so far."""

    received: int = 0
    emitted: int = 0
    lost: int = 0
    duplicates: int = 0
    late: int = 0
    reordered: int = 0
    resyncs: int = 0

    @property
    def loss_percent(self) -> float:
        total = self.emitted + self.lost
        return (self.lost / total * 100.0) if total else 0.0


class JitterBuffer:
    """Sequence-ordered playout buffer for fixed-duration audio frames."""

    def __init__(self, depth: int = DEFAULT_DEPTH, max_gap: int = DEFAULT_MAX_GAP):
        self._depth = max(0, depth)
        self._max_gap = max(1, max_gap)
        self._frames: dict[int, bytes] = {}
        self._next: Optional[int] = None
        self._highest: Optional[int] = None
        self._stats = JitterStats()

    @property
    def stats(self) -> JitterStats:
        return self._stats

    @property
    def pending(self) -> int:
        """Frames currently held back (each one is a frame of added latency)."""
        return len(self._frames)

    @property
    def depth(self) -> int:
        return self._depth

    def reset(self) -> None:
        """Forget the stream. Counters stay — they describe the whole session."""
        self._frames = {}
        self._next = None
        self._highest = None

    def push(self, sequence: int, payload: bytes) -> list[Optional[bytes]]:
        """Accept one frame; return the frames now ready to play, in order.

        A ``None`` entry marks a frame that never arrived.
        """
        sequence &= 0xFFFFFFFF
        self._stats = replace(self._stats, received=self._stats.received + 1)

        if self._next is None:
            self._start_at(sequence)
        elif seq_diff(sequence, self._next) > self._max_gap:
            # New stream: drain what we still hold, then follow the new counter.
            drained = self.flush()
            self._start_at(sequence)
            self._stats = replace(self._stats, resyncs=self._stats.resyncs + 1)
            self._frames[sequence] = payload
            return drained + self._drain_to_depth()
        elif seq_diff(sequence, self._next) < 0:
            # Already played past this slot — playing it now would be audible
            # as a stutter, and it can no longer be ordered correctly.
            self._stats = replace(self._stats, late=self._stats.late + 1)
            return []
        elif sequence in self._frames:
            self._stats = replace(self._stats, duplicates=self._stats.duplicates + 1)
            return []

        if self._highest is not None and seq_diff(sequence, self._highest) < 0:
            self._stats = replace(self._stats, reordered=self._stats.reordered + 1)
        if self._highest is None or seq_diff(sequence, self._highest) > 0:
            self._highest = sequence

        self._frames[sequence] = payload
        return self._drain_to_depth()

    def flush(self) -> list[Optional[bytes]]:
        """Emit every held frame in order, filling internal holes with None."""
        if not self._frames:
            return []
        out: list[Optional[bytes]] = []
        while self._frames:
            out.extend(self._emit_one())
        return out

    def _start_at(self, sequence: int) -> None:
        self._frames = {}
        self._next = sequence
        self._highest = sequence

    def _drain_to_depth(self) -> list[Optional[bytes]]:
        out: list[Optional[bytes]] = []
        while len(self._frames) > self._depth:
            out.extend(self._emit_one())
        return out

    def _emit_one(self) -> list[Optional[bytes]]:
        """Advance the playout point by one frame."""
        assert self._next is not None
        current = self._next
        self._next = (current + 1) & 0xFFFFFFFF
        payload = self._frames.pop(current, None)
        if payload is None:
            self._stats = replace(self._stats, lost=self._stats.lost + 1)
            return [None]
        self._stats = replace(self._stats, emitted=self._stats.emitted + 1)
        return [payload]
