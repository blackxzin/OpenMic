"""Tests for the stream-quality counters shown in the desktop UI.

Bitrate and jitter are computed from arrival timestamps, so the collector
takes an injectable clock instead of reading time.monotonic() — otherwise
these assertions would depend on how fast the test machine runs.
"""

import unittest

from openmic.stream_stats import StreamStatsCollector


class TestStreamStatsCollector(unittest.TestCase):
    def test_bitrate_reflects_bytes_in_the_window(self):
        collector = StreamStatsCollector(window_seconds=2.0)
        # 100 packets of 60 bytes over the window = 48000 bits / 2 s = 24 kbps.
        for index in range(100):
            collector.record_packet(60, now=index * 0.02)
        snapshot = collector.snapshot(now=2.0)
        self.assertAlmostEqual(snapshot.bitrate_kbps, 24.0, places=1)
        self.assertEqual(snapshot.packets, 100)

    def test_packets_outside_the_window_stop_counting_toward_bitrate(self):
        collector = StreamStatsCollector(window_seconds=1.0)
        collector.record_packet(1000, now=0.0)
        snapshot = collector.snapshot(now=10.0)
        self.assertEqual(snapshot.bitrate_kbps, 0.0)
        self.assertFalse(snapshot.receiving)

    def test_evenly_spaced_packets_have_near_zero_jitter(self):
        collector = StreamStatsCollector(frame_ms=20.0)
        for index in range(50):
            collector.record_packet(60, now=index * 0.02)
        self.assertLess(collector.snapshot(now=1.0).jitter_ms, 0.5)

    def test_uneven_arrival_raises_jitter(self):
        collector = StreamStatsCollector(frame_ms=20.0)
        arrival = 0.0
        for index in range(50):
            arrival += 0.02 if index % 2 else 0.08  # 60 ms of bunching
            collector.record_packet(60, now=arrival)
        self.assertGreater(collector.snapshot(now=arrival).jitter_ms, 10.0)

    def test_reset_clears_counters(self):
        collector = StreamStatsCollector()
        collector.record_packet(60, now=0.0)
        collector.reset()
        snapshot = collector.snapshot(now=0.1)
        self.assertEqual(snapshot.packets, 0)
        self.assertEqual(snapshot.jitter_ms, 0.0)

    def test_snapshot_passes_through_buffer_counters(self):
        collector = StreamStatsCollector()
        snapshot = collector.snapshot(lost=3, duplicates=1, reordered=2, loss_percent=1.5, buffer_ms=60.0)
        self.assertEqual((snapshot.lost, snapshot.duplicates, snapshot.reordered), (3, 1, 2))
        self.assertEqual(snapshot.loss_percent, 1.5)
        self.assertEqual(snapshot.buffer_ms, 60.0)


if __name__ == "__main__":
    unittest.main()
