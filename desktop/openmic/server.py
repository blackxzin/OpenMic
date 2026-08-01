"""UDP server that receives PCM audio from the phone and plays it into the virtual sink."""

import asyncio
import queue
from typing import Callable, Optional

import sounddevice as sd

from . import protocol


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
        on_hello: Optional[Callable[[tuple, str], None]],
        on_bye: Optional[Callable[[tuple], None]],
    ):
        self._bridge = bridge
        self._on_hello = on_hello
        self._on_bye = on_bye

    def datagram_received(self, data: bytes, addr) -> None:
        try:
            packet_type, payload = protocol.unpack(data)
        except ValueError:
            return
        if packet_type == protocol.HELLO:
            if self._on_hello:
                self._on_hello(addr, payload)
        elif packet_type == protocol.AUDIO:
            _, pcm = payload
            self._bridge.push_audio(pcm)
        elif packet_type == protocol.BYE:
            if self._on_bye:
                self._on_bye(addr)


async def run_server(
    host: str,
    port: int,
    bridge: AudioBridge,
    on_hello: Optional[Callable[[tuple, str], None]] = None,
    on_bye: Optional[Callable[[tuple], None]] = None,
):
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(
        lambda: _MicServerProtocol(bridge, on_hello, on_bye),
        local_addr=(host, port),
    )
    return transport
