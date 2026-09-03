"""Live-socket test of the server: real UDP, real pairing, real gating.

Everything else mocks the transport, so this is the only test that proves the
datagram path works end to end — including that an unpaired sender on the
same socket gets nothing through.
"""

import asyncio
import socket
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock

import numpy as np  # noqa: F401  (server imports numpy)

from openmic import protocol as p
from openmic.pairing import PairingStore
from openmic.server import AudioBridge, run_server

_HOST = "127.0.0.1"
_SETTLE = 0.05  # seconds for the event loop to process a datagram


class TestServerOverUdp(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.bridge = MagicMock(spec=AudioBridge)
        self.transport = await run_server(
            _HOST,
            0,  # ephemeral: never collides with a real install on this machine
            self.bridge,
            store=PairingStore(path=Path(self._tmp.name) / "devices.enc"),
        )
        self.addCleanup(self.transport.close)
        self.port = self.transport.get_extra_info("socket").getsockname()[1]

    def _client(self) -> socket.socket:
        client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        client.settimeout(2.0)
        self.addCleanup(client.close)
        return client

    async def _send(self, client: socket.socket, packet: bytes) -> None:
        client.sendto(packet, (_HOST, self.port))
        await asyncio.sleep(_SETTLE)

    async def _pair(self, client: socket.socket) -> None:
        await self._send(client, p.pack_hello("Phone"))
        challenge, _ = client.recvfrom(2048)
        self.assertEqual(challenge[0], p.PAIR_CHAL)
        pin = challenge[1:].decode("ascii")
        await self._send(client, p.pack_pair_response(pin))
        ack, _ = client.recvfrom(2048)
        self.assertEqual(ack[0], p.PAIR_ACK)

    async def test_paired_client_streams_audio(self):
        client = self._client()
        await self._pair(client)
        await self._send(client, p.pack_audio_opus(0, b"\x01\x02\x03"))
        self.bridge.push_opus.assert_called_once_with(0, b"\x01\x02\x03")

    async def test_unpaired_client_audio_is_ignored(self):
        client = self._client()
        await self._send(client, p.pack_audio_opus(0, b"\x01\x02\x03"))
        self.bridge.push_opus.assert_not_called()

    async def test_malformed_datagram_does_not_kill_the_server(self):
        client = self._client()
        await self._send(client, b"\xff\xff\xff")       # unknown type
        await self._send(client, bytes([p.AUDIO_OPUS]))  # truncated header
        await self._pair(client)                         # server still alive
        await self._send(client, p.pack_audio_opus(1, b"\x04"))
        self.bridge.push_opus.assert_called_once_with(1, b"\x04")

    async def test_bye_stops_further_audio(self):
        client = self._client()
        await self._pair(client)
        await self._send(client, p.pack_bye())
        await self._send(client, p.pack_audio_opus(2, b"\x05"))
        self.bridge.push_opus.assert_not_called()


if __name__ == "__main__":
    unittest.main()
