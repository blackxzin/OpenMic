"""Round-trip and cross-implementation tests for the wire protocol.

Stdlib `unittest` only (no pytest in this env). Run:
    python3 -m unittest discover -s tests -v
"""

import unittest

from openmic import protocol as p

# Must stay in sync with mobile/lib/protocol.dart constants.
DART_HELLO = 0x01
DART_AUDIO = 0x02
DART_BYE = 0x03
DART_PAIR_CHAL = 0x04
DART_PAIR_RESP = 0x05
DART_PAIR_ACK = 0x06
DART_AUDIO_OPUS = 0x07
DART_VERSION = 0x01
DART_DEVICE_ID_LEN = 16
DART_AUTH_TOKEN_LEN = 16
DART_PIN_LEN = 6
DART_SAMPLE_RATE = 48000
DART_OPUS_BITRATE = 24000
DART_OPUS_FRAME_SIZE_MS = 20
DART_OPUS_FRAME_SAMPLES = 960


class TestConstantsParity(unittest.TestCase):
    """Python and Dart must define identical wire constants."""

    def test_packet_types_match(self):
        self.assertEqual(p.HELLO, DART_HELLO)
        self.assertEqual(p.AUDIO, DART_AUDIO)
        self.assertEqual(p.BYE, DART_BYE)
        self.assertEqual(p.PAIR_CHAL, DART_PAIR_CHAL)
        self.assertEqual(p.PAIR_RESP, DART_PAIR_RESP)
        self.assertEqual(p.PAIR_ACK, DART_PAIR_ACK)
        self.assertEqual(p.AUDIO_OPUS, DART_AUDIO_OPUS)

    def test_protocol_version_matches(self):
        self.assertEqual(p.PROTOCOL_VERSION, DART_VERSION)

    def test_field_lengths_match(self):
        self.assertEqual(p.DEVICE_ID_LEN, DART_DEVICE_ID_LEN)
        self.assertEqual(p.AUTH_TOKEN_LEN, DART_AUTH_TOKEN_LEN)
        self.assertEqual(p.PIN_LEN, DART_PIN_LEN)

    def test_audio_params_match(self):
        self.assertEqual(p.SAMPLE_RATE, DART_SAMPLE_RATE)
        self.assertEqual(p.OPUS_BITRATE, DART_OPUS_BITRATE)
        self.assertEqual(p.OPUS_FRAME_SIZE_MS, DART_OPUS_FRAME_SIZE_MS)
        self.assertEqual(p.OPUS_FRAME_SAMPLES, DART_OPUS_FRAME_SAMPLES)


class TestHello(unittest.TestCase):
    def test_pack_unpaired_v1(self):
        name = "Pixel"
        pkt = p.pack_hello(name)
        self.assertEqual(pkt[0], p.HELLO)
        self.assertEqual(pkt[1], p.PROTOCOL_VERSION)
        self.assertEqual(pkt[2:].decode("utf-8"), name)

    def test_pack_unpaired_name_bytes_exact(self):
        # Byte layout the Dart Protocol.packHello produces.
        name = "Android"
        expected = bytes([DART_HELLO, DART_VERSION]) + name.encode("utf-8")
        self.assertEqual(p.pack_hello(name), expected)

    def test_unpack_unpaired_v1(self):
        pkt = p.pack_hello("iPhone")
        ptype, (version, dev_id, auth, name) = p.unpack(pkt)
        self.assertEqual(ptype, p.HELLO)
        self.assertEqual(version, p.PROTOCOL_VERSION)
        self.assertIsNone(dev_id)
        self.assertIsNone(auth)
        self.assertEqual(name, "iPhone")

    def test_pack_paired_layout(self):
        device_id = bytes(range(16))
        auth_token = bytes(range(16, 32))
        name = "Pixel"
        pkt = p.pack_hello_paired(device_id, auth_token, name)
        # [HELLO, VER, 16 dev_id, 16 auth, name]
        self.assertEqual(len(pkt), 2 + 16 + 16 + len(name))
        self.assertEqual(pkt[0], p.HELLO)
        self.assertEqual(pkt[1], p.PROTOCOL_VERSION)
        self.assertEqual(pkt[2:18], device_id)
        self.assertEqual(pkt[18:34], auth_token)
        self.assertEqual(pkt[34:], name.encode("utf-8"))

    def test_unpack_paired_v1(self):
        device_id = bytes(range(16))
        auth_token = bytes(range(16, 32))
        pkt = p.pack_hello_paired(device_id, auth_token, "Pixel")
        ptype, (version, dev_id, auth, name) = p.unpack(pkt)
        self.assertEqual(ptype, p.HELLO)
        self.assertEqual(version, p.PROTOCOL_VERSION)
        self.assertEqual(dev_id, device_id)
        self.assertEqual(auth, auth_token)
        self.assertEqual(name, "Pixel")

    def test_paired_with_empty_name_still_paired(self):
        # Edge: name shorter than 32 bytes must not be misread as unpaired.
        device_id = bytes(range(16))
        auth_token = bytes(range(16, 32))
        pkt = p.pack_hello_paired(device_id, auth_token, "")
        ptype, (version, dev_id, auth, name) = p.unpack(pkt)
        self.assertEqual(dev_id, device_id)
        self.assertEqual(auth, auth_token)
        self.assertEqual(name, "")

    def test_hello_v0_backward_compat(self):
        pkt = p.pack_hello_v0("Legacy")
        ptype, (version, dev_id, auth, name) = p.unpack(pkt)
        self.assertEqual(ptype, p.HELLO)
        self.assertEqual(version, 0)
        self.assertIsNone(dev_id)
        self.assertEqual(name, "Legacy")

    def test_hello_too_short_rejected(self):
        with self.assertRaises(ValueError):
            p.unpack(bytes([p.HELLO, p.PROTOCOL_VERSION]))  # 2 bytes, no name


class TestAudio(unittest.TestCase):
    def test_pack_audio_pcm_layout(self):
        pcm = bytes([0x01, 0x02, 0x03, 0x04])
        pkt = p.pack_audio(0x01020304, pcm)
        self.assertEqual(pkt[0], p.AUDIO)
        # 4-byte big-endian sequence
        self.assertEqual(pkt[1:5], bytes([0x01, 0x02, 0x03, 0x04]))
        self.assertEqual(pkt[5:], pcm)

    def test_pack_audio_opus_layout(self):
        opus = bytes(range(10))
        pkt = p.pack_audio_opus(42, opus)
        self.assertEqual(pkt[0], p.AUDIO_OPUS)
        self.assertEqual(pkt[1:5], bytes([0x00, 0x00, 0x00, 0x2A]))
        self.assertEqual(pkt[5:], opus)

    def test_unpack_audio_pcm(self):
        pkt = p.pack_audio(7, b"\x00\x01\x00\x02")
        ptype, (seq, pcm) = p.unpack(pkt)
        self.assertEqual(ptype, p.AUDIO)
        self.assertEqual(seq, 7)
        self.assertEqual(pcm, b"\x00\x01\x00\x02")

    def test_unpack_audio_opus(self):
        opus = bytes(range(20))
        pkt = p.pack_audio_opus(0xFFFFFFFF, opus)
        ptype, (seq, data) = p.unpack(pkt)
        self.assertEqual(ptype, p.AUDIO_OPUS)
        self.assertEqual(seq, 0xFFFFFFFF)
        self.assertEqual(data, opus)

    def test_audio_sequence_big_endian(self):
        # Dart uses Endian.big; Python struct ">I".
        pkt = p.pack_audio(1, b"")
        self.assertEqual(pkt[1:5], b"\x00\x00\x00\x01")


class TestBye(unittest.TestCase):
    def test_pack_bye(self):
        self.assertEqual(p.pack_bye(), bytes([p.BYE]))

    def test_unpack_bye(self):
        ptype, payload = p.unpack(p.pack_bye())
        self.assertEqual(ptype, p.BYE)
        self.assertIsNone(payload)


class TestPairing(unittest.TestCase):
    def test_pack_pair_challenge(self):
        pin = "123456"
        pkt = p.pack_pair_challenge(pin)
        self.assertEqual(pkt, bytes([p.PAIR_CHAL]) + pin.encode("ascii"))

    def test_unpack_pair_challenge(self):
        pkt = p.pack_pair_challenge("998877")
        ptype, pin = p.unpack(pkt)
        self.assertEqual(ptype, p.PAIR_CHAL)
        self.assertEqual(pin, "998877")

    def test_pack_pair_response(self):
        self.assertEqual(p.pack_pair_response("123456"), bytes([p.PAIR_RESP]) + b"123456")

    def test_unpack_pair_response(self):
        ptype, pin = p.unpack(p.pack_pair_response("998877"))
        self.assertEqual(ptype, p.PAIR_RESP)
        self.assertEqual(pin, "998877")

    def test_unpack_pair_response_legacy_empty(self):
        # v0 client cannot echo the PIN; payload must be empty, not None.
        ptype, pin = p.unpack(bytes([p.PAIR_RESP]))
        self.assertEqual(ptype, p.PAIR_RESP)
        self.assertEqual(pin, "")

    def test_pack_pair_ack_layout(self):
        device_id = bytes(range(16))
        auth_token = bytes(range(16, 32))
        pkt = p.pack_pair_ack(device_id, auth_token)
        self.assertEqual(pkt[0], p.PAIR_ACK)
        self.assertEqual(pkt[1:17], device_id)
        self.assertEqual(pkt[17:33], auth_token)

    def test_unpack_pair_ack(self):
        device_id = bytes(range(16))
        auth_token = bytes(range(16, 32))
        pkt = p.pack_pair_ack(device_id, auth_token)
        ptype, (dev_id, auth) = p.unpack(pkt)
        self.assertEqual(ptype, p.PAIR_ACK)
        self.assertEqual(dev_id, device_id)
        self.assertEqual(auth, auth_token)

    def test_pair_ack_too_short_rejected(self):
        with self.assertRaises(ValueError):
            p.unpack(bytes([p.PAIR_ACK]) + bytes(range(10)))

    def test_pin_always_six_digits(self):
        for _ in range(100):
            pin = p.generate_pin()
            self.assertEqual(len(pin), p.PIN_LEN)
            self.assertTrue(pin.isdigit())

    def test_generate_device_id_and_auth_token_length(self):
        self.assertEqual(len(p.generate_device_id()), p.DEVICE_ID_LEN)
        self.assertEqual(len(p.generate_auth_token()), p.AUTH_TOKEN_LEN)

    def test_generated_ids_are_random(self):
        self.assertNotEqual(p.generate_device_id(), p.generate_device_id())
        self.assertNotEqual(p.generate_auth_token(), p.generate_auth_token())


class TestUnknownAndEmpty(unittest.TestCase):
    def test_empty_packet_rejected(self):
        with self.assertRaises(ValueError):
            p.unpack(b"")

    def test_unknown_type_rejected(self):
        with self.assertRaises(ValueError):
            p.unpack(bytes([0xFF]))


if __name__ == "__main__":
    unittest.main()
