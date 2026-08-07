"""Integration test for pairing validation in _MicServerProtocol.

Exercises the PIN-echo handshake without a network: feed datagrams into a
protocol instance with a mock transport + bridge, assert we only ever emit a
PAIR_ACK when the echoed PIN matches, and that wrong/empty PINs are rejected."""

import unittest
from unittest.mock import MagicMock

import numpy as np  # noqa: F401  (server imports numpy)

from openmic.server import AudioBridge, _MicServerProtocol
from openmic import protocol as p


class _FakeTransport:
    def __init__(self):
        self.sent = []

    def sendto(self, data, addr):
        self.sent.append((addr, data))


class _PairingCase(unittest.TestCase):
    def setUp(self):
        self.transport = _FakeTransport()
        self.bridge = MagicMock(spec=AudioBridge)
        self.hello_noop = MagicMock()
        self.protocol = _MicServerProtocol(
            self.bridge,
            on_hello=self.hello_noop,
            on_bye=None,
            on_pairing_request=None,
        )
        self.protocol.connection_made(self.transport)
        self.addr = ("10.0.0.5", 4000)

    def _trigger_challenge(self):
        self.protocol.datagram_received(p.pack_hello("Phone"), self.addr)
        chal = next(d for a, d in self.transport.sent if d[0] == p.PAIR_CHAL)
        pin = chal[1:].decode("ascii")
        return pin

    def _acks_sent(self):
        return [d for a, d in self.transport.sent if d[0] == p.PAIR_ACK]


class TestPairingHandshake(_PairingCase):
    def test_correct_pin_acks(self):
        pin = self._trigger_challenge()
        self.protocol.datagram_received(p.pack_pair_response(pin), self.addr)
        acks = self._acks_sent()
        self.assertEqual(len(acks), 1)
        self.assertEqual(len(acks[0]), 1 + p.DEVICE_ID_LEN + p.AUTH_TOKEN_LEN)
        self.hello_noop.assert_called_once()  # UI notified

    def test_wrong_pin_rejected(self):
        self._trigger_challenge()
        self.protocol.datagram_received(p.pack_pair_response("999999"), self.addr)
        self.assertEqual(self._acks_sent(), [])
        self.hello_noop.assert_not_called()

    def test_empty_pin_rejected(self):
        self._trigger_challenge()
        self.protocol.datagram_received(bytes([p.PAIR_RESP]), self.addr)  # no pin
        self.assertEqual(self._acks_sent(), [])

    def test_unknown_addr_rejected(self):
        self.protocol.datagram_received(
            p.pack_pair_response("123456"), ("10.0.0.9", 99)
        )
        self.assertEqual(self._acks_sent(), [])


if __name__ == "__main__":
    unittest.main()