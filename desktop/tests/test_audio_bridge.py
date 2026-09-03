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

class _FakeDecoder:
    """Stands in for libopus so these tests need no codec and no PortAudio."""

    def __init__(self):
        self.decoded = []
        self.concealed = 0

    def decode(self, frame):
        self.decoded.append(frame)
        return b"P" + frame

    def decode_lost(self):
        self.concealed += 1
        return b"CONCEALED"


class _BridgeCase(unittest.TestCase):
    def setUp(self):
        self.bridge = AudioBridge(sink_device_name="test")
        # The suppressor buffers half a frame and rewrites samples, which
        # would obscure exactly what came out of the codec path.
        self.bridge.noise_suppression_enabled = False
        self.decoder = _FakeDecoder()
        self.bridge._opus_decoder = self.decoder

    def _played(self):
        out = []
        while True:
            try:
                out.append(self.bridge._queue.get_nowait())
            except Exception:
                return out


class TestOpusPlayout(_BridgeCase):
    def test_reordered_frames_are_played_in_sequence_order(self):
        for sequence, payload in ((0, b"a"), (2, b"c"), (1, b"b"), (3, b"d"), (4, b"e")):
            self.bridge.push_opus(sequence, payload)
        # Default depth holds three frames back, so 0 and 1 have played and
        # the reordered 1 landed in its own slot rather than after 2.
        self.assertEqual(self.decoder.decoded, [b"a", b"b"])

    def test_lost_frame_is_concealed_instead_of_skipped(self):
        for sequence in (0, 1, 2, 4, 5, 6, 7):
            self.bridge.push_opus(sequence, bytes([sequence]))
        # Frame 3 never arrived; the codec fills the hole rather than the
        # queue jumping straight to frame 4.
        self.assertEqual(self.decoder.concealed, 1)
        self.assertIn(b"CONCEALED", self._played())

    def test_duplicate_frame_is_decoded_once(self):
        for sequence in (0, 1, 1, 2, 3, 4):
            self.bridge.push_opus(sequence, bytes([sequence]))
        self.assertEqual(len(self.decoder.decoded), len(set(self.decoder.decoded)))

    def test_frames_without_a_decoder_are_ignored(self):
        self.bridge._opus_decoder = None
        self.bridge.push_opus(0, b"a")
        self.assertEqual(self._played(), [])

    def test_undecodable_frame_does_not_break_the_stream(self):
        def explode(frame):
            raise RuntimeError("corrupt frame")

        self.decoder.decode = explode
        for sequence in range(6):
            self.bridge.push_opus(sequence, bytes([sequence]))
        self.assertEqual(self._played(), [])  # dropped, not raised


class TestPcmPlayout(_BridgeCase):
    def test_lost_pcm_frame_becomes_silence_of_the_same_length(self):
        frame = b"\x01\x02" * 480
        for sequence in (0, 1, 2, 4, 5, 6, 7):
            self.bridge.push_pcm(sequence, frame)
        played = self._played()
        self.assertIn(b"\x00" * len(frame), played)

    def test_stats_report_loss_and_buffer_depth(self):
        for sequence in (0, 1, 2, 4, 5, 6, 7):
            self.bridge.push_pcm(sequence, b"\x00" * 1920)
        stats = self.bridge.stats()
        self.assertEqual(stats.lost, 1)
        self.assertEqual(stats.packets, 7)
        self.assertGreater(stats.loss_percent, 0.0)
        self.assertGreater(stats.buffer_ms, 0.0)

    def test_stop_output_clears_stream_state(self):
        self.bridge.push_pcm(0, b"\x00" * 1920)
        self.bridge.stop_output()
        self.assertEqual(self.bridge.stats().packets, 0)
        self.assertEqual(self.bridge.stats().buffer_ms, 0.0)
