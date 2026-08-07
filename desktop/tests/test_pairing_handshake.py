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


class TestTrustedReconnect(_PairingCase):
    """After pairing, a reconnect HELLO must get a reply so the mobile's
    connect handshake resolves — it does NOT sit and time out forever."""

    def test_trusted_hello_gets_hello_reply(self):
        # Simulate an already-paired device: store its creds first.
        dev_id = bytes(range(16))
        auth = bytes(range(16, 32))
        self.protocol._store.add(dev_id, auth, "Phone")

        self.protocol.datagram_received(
            p.pack_hello_paired(dev_id, auth, "Phone"), self.addr
        )

        # Must have sent exactly one HELLO datagram back (no PIN challenge).
        replies = [d for a, d in self.transport.sent if d[0] == p.HELLO]
        self.assertEqual(len(replies), 1)
        # And it must not contain credentials (so the phone does not re-key).
        ptype, (ver, rid, rauth, rname) = p.unpack(replies[0])
        self.assertEqual(ptype, p.HELLO)
        self.assertEqual(ver, p.PROTOCOL_VERSION)
        self.assertIsNone(rid)
        self.assertIsNone(rauth)
        self.assertEqual(rname, "Phone")

    def test_trusted_hello_invalid_token_gets_challenge(self):
        self.protocol._store.add(bytes(range(16)), bytes(range(16, 32)), "Phone")
        self.protocol.datagram_received(
            p.pack_hello_paired(bytes(range(16)), b"\x00" * 16, "Fake"),
            self.addr,
        )
        chals = [d for a, d in self.transport.sent if d[0] == p.PAIR_CHAL]
        self.assertEqual(len(chals), 1)


if __name__ == "__main__":
    unittest.main()