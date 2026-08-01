"""UDP server that receives PCM audio from the phone and plays it into the virtual sink."""

import asyncio
import logging
import queue
from typing import Callable, Optional

import sounddevice as sd

from . import protocol
from .pairing import PairingStore, verify_pairing

_log = logging.getLogger(__name__)


class AudioBridge:
    """Feeds received PCM chunks into an output stream targeting the virtual sink."""

    def __init__(self, sink_device_name: str):
        self._sink_device_name = sink_device_name
        self._queue: "queue.Queue[bytes]" = queue.Queue(maxsize=100)
        self._stream: Optional[sd.RawOutputStream] = None

    def start_output(self) -> None:
        # PortAudio caches its device list at init time, so a sink created after this
        # process started (which is always, since we create it ourselves) is invisible
        # until we force it to rescan.
        sd._terminate()
        sd._initialize()
        device_index = self._find_device_index(self._sink_device_name)
        self._stream = sd.RawOutputStream(
            samplerate=protocol.SAMPLE_RATE,
            channels=protocol.CHANNELS,
            dtype="int16",
            device=device_index,
            callback=self._audio_callback,
        )
        self._stream.start()

    def stop_output(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def push_audio(self, pcm: bytes) -> None:
        try:
            self._queue.put_nowait(pcm)
        except queue.Full:
            pass  # falling behind: drop this chunk rather than build up latency

    def _audio_callback(self, outdata, frames, time_info, status):
        needed = frames * protocol.SAMPLE_WIDTH * protocol.CHANNELS
        try:
            chunk = self._queue.get_nowait()
        except queue.Empty:
            outdata[:] = b"\x00" * needed
            return
        if len(chunk) < needed:
            chunk = chunk + b"\x00" * (needed - len(chunk))
        elif len(chunk) > needed:
            chunk = chunk[:needed]
        outdata[:] = chunk

    @staticmethod
    def _find_device_index(name_substring: str) -> int:
        for index, device in enumerate(sd.query_devices()):
            if name_substring.lower() in device["name"].lower() and device["max_output_channels"] > 0:
                return index
        raise RuntimeError(f"output device matching '{name_substring}' not found")


class _MicServerProtocol(asyncio.DatagramProtocol):
    def __init__(
        self,
        bridge: AudioBridge,
        on_hello: Optional[Callable[[tuple, str, int, bytes, bytes], None]],
        on_bye: Optional[Callable[[tuple], None]],
        on_pairing_request: Optional[Callable[[tuple, str], None]],
    ):
        self._bridge = bridge
        self._on_hello = on_hello
        self._on_bye = on_bye
        self._on_pairing_request = on_pairing_request
        self.transport = None
        self._store = PairingStore()
        self._pending_pairing: dict = {}  # addr -> {"pin": str, "device_name": str}

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data: bytes, addr) -> None:
        try:
            packet_type, payload = protocol.unpack(data)
        except ValueError:
            return

        if packet_type == protocol.HELLO:
            self._handle_hello(addr, payload)
        elif packet_type == protocol.AUDIO:
            _, pcm = payload
            self._bridge.push_audio(pcm)
        elif packet_type == protocol.BYE:
            if self._on_bye:
                self._on_bye(addr)
        elif packet_type == protocol.PAIR_RESP:
            self._handle_pair_response(addr)
        elif packet_type == protocol.PAIR_CHAL:
            # Shouldn't receive this on desktop, but handle gracefully
            _log.debug("Unexpected PAIR_CHAL from %s", addr)

    def _handle_hello(self, addr, payload) -> None:
        # payload is (version, device_id, auth_token, name)
        version, device_id, auth_token, name = payload

        if device_id is not None and auth_token is not None:
            # Paired HELLO - verify credentials
            if verify_pairing(device_id, auth_token, self._store):
                stored_name = self._store.get_name(device_id) or name
                _log.info("Trusted device connected: %s (%s)", stored_name, addr[0])
                if self._on_hello:
                    self._on_hello(addr, stored_name, version, device_id, auth_token)
                return
            else:
                _log.warning("Invalid auth token from %s (%s)", name, addr[0])
                # Fall through to new device pairing

        # New/unpaired device - send pairing challenge
        pin = protocol.generate_pin()
        self._pending_pairing[addr] = {"pin": pin, "device_name": name}
        challenge = protocol.pack_pair_challenge(pin)
        self.transport.sendto(challenge, addr)
        _log.info("Pairing challenge sent to %s (%s): PIN=%s", name, addr[0], pin)

        if self._on_pairing_request:
            self._on_pairing_request(addr, pin)

    def _handle_pair_response(self, addr) -> None:
        pending = self._pending_pairing.pop(addr, None)
        if not pending:
            _log.warning("PAIR_RESP from unknown addr: %s", addr)
            return

        # Generate device credentials
        device_id = protocol.generate_device_id()
        auth_token = protocol.generate_auth_token()

        # Store credentials
        self._store.add(device_id, auth_token, pending["device_name"])

        # Send ACK with credentials
        ack = protocol.pack_pair_ack(device_id, auth_token)
        self.transport.sendto(ack, addr)
        _log.info("Device paired successfully: %s (%s)", pending["device_name"], addr[0])

        # Notify UI
        if self._on_hello:
            self._on_hello(addr, pending["device_name"], protocol.PROTOCOL_VERSION, device_id, auth_token)


async def run_server(
    host: str,
    port: int,
    bridge: AudioBridge,
    on_hello: Optional[Callable[[tuple, str, int, bytes, bytes], None]] = None,
    on_bye: Optional[Callable[[tuple], None]] = None,
    on_pairing_request: Optional[Callable[[tuple, str], None]] = None,
):
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(
        lambda: _MicServerProtocol(bridge, on_hello, on_bye, on_pairing_request),
        local_addr=(host, port),
    )
    return transport