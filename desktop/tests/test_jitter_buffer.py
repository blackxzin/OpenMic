"""Tests for the reorder/dedupe/gap-detect buffer in front of the decoder.

The phone stamps every audio packet with a 32-bit sequence number, and UDP
delivers them reordered, duplicated or not at all. These tests pin the
buffer's contract: frames come out in sequence order, duplicates never do,
and a hole in the sequence surfaces as an explicit None so the caller can
run packet-loss concealment instead of playing the next frame early.
"""

import unittest

from openmic.jitter_buffer import SEQ_SPACE, JitterBuffer, seq_diff


class TestSeqDiff(unittest.TestCase):
    def test_plain_distance(self):
        self.assertEqual(seq_diff(10, 7), 3)
        self.assertEqual(seq_diff(7, 10), -3)

    def test_wraparound_is_a_small_forward_distance(self):
        # 0 arriving after 0xFFFFFFFF is the next frame, not 4 billion late.
        self.assertEqual(seq_diff(0, SEQ_SPACE - 1), 1)
        self.assertEqual(seq_diff(SEQ_SPACE - 1, 0), -1)


class TestJitterBuffer(unittest.TestCase):
    def test_holds_frames_until_depth_is_reached(self):
        buffer = JitterBuffer(depth=2)
        self.assertEqual(buffer.push(0, b"a"), [])
        self.assertEqual(buffer.push(1, b"b"), [])
        # Third frame pushes the oldest out: depth 2 keeps two in reserve.
        self.assertEqual(buffer.push(2, b"c"), [b"a"])

    def test_reordered_frame_is_emitted_in_sequence_order(self):
        buffer = JitterBuffer(depth=1)
        self.assertEqual(buffer.push(0, b"a"), [])
        self.assertEqual(buffer.push(2, b"c"), [b"a"])
        # 1 arrives after 2 but still before its playout point, so it plays
        # in its own slot rather than being thrown away.
        self.assertEqual(buffer.push(1, b"b"), [b"b"])
        self.assertEqual(buffer.push(3, b"d"), [b"c"])
        self.assertEqual(buffer.stats.reordered, 1)

    def test_gap_is_reported_as_none(self):
        buffer = JitterBuffer(depth=1)
        self.assertEqual(buffer.push(0, b"a"), [])
        self.assertEqual(buffer.push(2, b"c"), [b"a"])
        # Frame 1 never arrived: the hole surfaces as None right before
        # frame 2 plays, so the caller can conceal it.
        self.assertEqual(buffer.push(3, b"d"), [None, b"c"])
        self.assertEqual(buffer.stats.lost, 1)

    def test_duplicate_frame_is_dropped(self):
        buffer = JitterBuffer(depth=1)
        buffer.push(0, b"a")
        self.assertEqual(buffer.push(0, b"a"), [])
        self.assertEqual(buffer.stats.duplicates, 1)

    def test_frame_older_than_the_playout_point_is_dropped(self):
        buffer = JitterBuffer(depth=0)
        self.assertEqual(buffer.push(5, b"f"), [b"f"])
        self.assertEqual(buffer.push(4, b"e"), [])
        self.assertEqual(buffer.stats.late, 1)

    def test_large_jump_resyncs_instead_of_emitting_thousands_of_gaps(self):
        buffer = JitterBuffer(depth=0, max_gap=10)
        buffer.push(0, b"a")
        emitted = buffer.push(5000, b"z")
        # A phone that reconnected restarts its own counter; concealing 5000
        # frames of silence would stall audio for 100 seconds.
        self.assertEqual(emitted, [b"z"])
        self.assertEqual(buffer.stats.resyncs, 1)
        self.assertEqual(buffer.stats.lost, 0)

    def test_sequence_wraparound_keeps_playing(self):
        buffer = JitterBuffer(depth=0)
        buffer.push(SEQ_SPACE - 1, b"a")
        self.assertEqual(buffer.push(0, b"b"), [b"b"])
        self.assertEqual(buffer.stats.lost, 0)
        self.assertEqual(buffer.stats.resyncs, 0)

    def test_flush_drains_held_frames_in_order(self):
        buffer = JitterBuffer(depth=5)
        buffer.push(0, b"a")
        buffer.push(1, b"b")
        self.assertEqual(buffer.flush(), [b"a", b"b"])
        self.assertEqual(buffer.pending, 0)

    def test_reset_forgets_the_stream(self):
        buffer = JitterBuffer(depth=1)
        buffer.push(9, b"a")
        buffer.reset()
        self.assertEqual(buffer.pending, 0)
        # A fresh stream starts wherever the next packet says it does.
        self.assertEqual(buffer.push(100, b"b"), [])


if __name__ == "__main__":
    unittest.main()
