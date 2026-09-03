"""Only a device that completed the handshake may push audio.

Pairing authenticates HELLO, but audio arrives as bare UDP datagrams on the
same port. Without a source check, any host on the same WiFi could inject
sound into the virtual microphone — no PIN, no token, no pairing — and the
desktop would happily play it into whatever call is open.
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock

import numpy as np  # noqa: F401  (server imports numpy)

from openmic import protocol as p
from openmic.pairing import PairingStore
from openmic.server import AUDIO_SOURCE_TTL, AudioBridge, _MicServerProtocol


class _FakeTransport:
    def __init__(self):
        self.sent = []

    def sendto(self, data, addr):
        self.sent.append((addr, data))


class _AuthorizationCase(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        # An injected store keeps the test off the real ~/.config/openmic file.
        self.store = PairingStore(path=Path(self._tmp.name) / "devices.enc")
        self.transport = _FakeTransport()
        self.bridge = MagicMock(spec=AudioBridge)
        self.protocol = _MicServerProtocol(
            self.bridge,
            on_hello=MagicMock(),
            on_bye=MagicMock(),
            on_pairing_request=None,
            store=self.store,
        )
        self.protocol.connection_made(self.transport)
        self.phone = ("10.0.0.5", 4000)
        self.attacker = ("10.0.0.99", 5555)

    def _pair(self, addr):
        self.protocol.datagram_received(p.pack_hello("Phone"), addr)
        challenge = next(d for _, d in self.transport.sent if d[0] == p.PAIR_CHAL)
        pin = challenge[1:].decode("ascii")
        self.protocol.datagram_received(p.pack_pair_response(pin), addr)

    def _send_opus(self, addr, sequence=0):
        self.protocol.datagram_received(p.pack_audio_opus(sequence, b"\x01\x02\x03"), addr)

    def _send_pcm(self, addr, sequence=0):
        self.protocol.datagram_received(p.pack_audio(sequence, b"\x00" * 1920), addr)


class TestUnauthorizedAudio(_AuthorizationCase):
    def test_opus_from_unknown_source_is_dropped(self):
        self._send_opus(self.attacker)
        self.bridge.push_opus.assert_not_called()

    def test_pcm_from_unknown_source_is_dropped(self):
        self._send_pcm(self.attacker)
        self.bridge.push_pcm.assert_not_called()

    def test_pending_pairing_does_not_authorize_audio(self):
        # Challenge sent but PIN never confirmed: still not a trusted device.
        self.protocol.datagram_received(p.pack_hello("Phone"), self.attacker)
        self._send_opus(self.attacker)
        self.bridge.push_opus.assert_not_called()

    def test_drops_are_counted_for_logging(self):
        for sequence in range(3):
            self._send_opus(self.attacker, sequence)
        self.assertEqual(self.protocol._unauthorized_audio, 3)


class TestAuthorizedAudio(_AuthorizationCase):
    def test_audio_flows_right_after_pairing(self):
        self._pair(self.phone)
        self._send_opus(self.phone, sequence=7)
        self.bridge.push_opus.assert_called_once_with(7, b"\x01\x02\x03")

    def test_audio_flows_after_a_trusted_reconnect(self):
        device_id = bytes(range(16))
        auth_token = bytes(range(16, 32))
        self.store.add(device_id, auth_token, "Phone")
        self.protocol.datagram_received(
            p.pack_hello_paired(device_id, auth_token, "Phone"), self.phone
        )
        self._send_pcm(self.phone, sequence=1)
        self.bridge.push_pcm.assert_called_once()

    def test_invalid_token_does_not_authorize(self):
        self.store.add(bytes(range(16)), bytes(range(16, 32)), "Phone")
        self.protocol.datagram_received(
            p.pack_hello_paired(bytes(range(16)), b"\x00" * 16, "Fake"), self.attacker
        )
        self._send_opus(self.attacker)
        self.bridge.push_opus.assert_not_called()

    def test_authorization_does_not_leak_to_another_address(self):
        self._pair(self.phone)
        self._send_opus(self.attacker)
        self.bridge.push_opus.assert_not_called()

    def test_bye_revokes_authorization(self):
        self._pair(self.phone)
        self.protocol.datagram_received(p.pack_bye(), self.phone)
        self._send_opus(self.phone)
        self.bridge.push_opus.assert_not_called()

    def test_authorization_expires_when_the_phone_goes_quiet(self):
        self._pair(self.phone)
        # Rewind the last-seen stamp past the TTL: same effect as the phone
        # disappearing without a BYE and something else taking its address.
        self.protocol._audio_sources[self.phone] -= AUDIO_SOURCE_TTL + 1
        self._send_opus(self.phone)
        self.bridge.push_opus.assert_not_called()

    def test_continuous_streaming_refreshes_the_ttl(self):
        self._pair(self.phone)
        self.protocol._audio_sources[self.phone] -= AUDIO_SOURCE_TTL - 1
        self._send_opus(self.phone, sequence=1)
        self._send_opus(self.phone, sequence=2)
        self.assertEqual(self.bridge.push_opus.call_count, 2)


if __name__ == "__main__":
    unittest.main()
