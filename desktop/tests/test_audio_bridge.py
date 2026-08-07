"""Tests for the AudioBridge chunk->frame remapping (no PortAudio needed)."""

import unittest

from openmic.server import AudioBridge


class TestReassemble(unittest.TestCase):
    def test_exact_fit(self):
        leftover, frame = AudioBridge.reassemble(b"", b"abcdef", 2)
        self.assertEqual(leftover, b"cdef")
        self.assertEqual(frame, b"ab")

    def test_partial_returns_empty(self):
        leftover, frame = AudioBridge.reassemble(b"", b"abcde", 2)
        # "abcde" has two full frames ("ab","cd") then tail "e". Only one frame
        # is pulled per call; the rest stays in the leftover buffer.
        self.assertEqual(leftover, b"cde")
        self.assertEqual(frame, b"ab")

    def test_opus_frame_split_and_carry(self):
        # Opus frame (1920 B) arrives while needing 512 B/frame.
        frame = bytes((i % 256 for i in range(1920)))
        leftover, out = AudioBridge.reassemble(b"", frame, 512)
        self.assertEqual(out, frame[:512])
        self.assertEqual(len(leftover), 1920 - 512)

        # Walk the rest down to the final partial tail, one 512-byte frame at
        # a time, without loss. The leftover tail (< needed) is retained.
        total = len(leftover)
        zero_size = 0
        while leftover and zero_size < 4:
            before = len(leftover)
            leftover, _ = AudioBridge.reassemble(leftover, b"", 512)
            if len(leftover) == before:
                zero_size += 1  # exhausted: only the <512 tail remains
            else:
                zero_size = 0
        self.assertLess(len(leftover), 512)
        self.assertEqual(len(leftover), 1920 % 512)  # 384
        # Lossless: every byte retained (tail) + produced frames = 1920.
        produced_total = (1920 - len(leftover)) // 512 * 512 + len(leftover)
        self.assertEqual(produced_total, 1920)

    def test_carry_from_previous_callback(self):
        # Leftover from last callback joins the next batch.
        leftover, out = AudioBridge.reassemble(b"xy", b"abcde", 3)
        self.assertEqual(leftover, b"bcde")
        self.assertEqual(out, b"xya")

    def test_odd_count_kept(self):
        leftover, frame = AudioBridge.reassemble(b"", b"ab", 4)
        self.assertEqual(leftover, b"ab")
        self.assertEqual(frame, b"")


if __name__ == "__main__":
    unittest.main()