"""UDP server that receives PCM audio from the phone and plays it into the virtual sink."""

import asyncio
import logging
import queue
import struct
import threading
import time as _time
from typing import Callable, Optional

import numpy as np
import sounddevice as sd

from . import protocol
from .noise_suppression import NoiseSuppressor
from .opus_codec import OpusDecoder, _OPUS_AVAILABLE
from .pairing import PairingStore, verify_pairing

_log = logging.getLogger(__name__)


class AudioBridge:
    """Feeds received PCM chunks into an output stream targeting the virtual sink."""

    def __init__(self, sink_device_name: str):
        self._sink_device_name = sink_device_name
        self._queue: "queue.Queue[bytes]" = queue.Queue(maxsize=100)
        self._stream: Optional[sd.RawOutputStream] = None
        self._opus_decoder: Optional[OpusDecoder] = None
        self._gain: float = 1.0
        self._gain_lock = threading.Lock()
        self._noise_suppressor = NoiseSuppressor(frame_size=protocol.OPUS_FRAME_SAMPLES)
        # Leftover PCM bytes not yet consumed by the audio callback. Opus frames
        # (960 samples) and PortAudio's callback size rarely align, so we resample
        # through a partial-frame accumulator instead of truncating each chunk
        # (which dropped most of every Opus frame).
        self._fragment = b""
        self._fragment_lock = threading.Lock()
        self._packet_count = 0

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

        if _OPUS_AVAILABLE:
            self._opus_decoder = OpusDecoder()
            _log.info("Opus decoder ready")
        else:
            _log.warning("Opus decoder unavailable — only raw PCM will work")

    @property
    def gain(self) -> float:
        with self._gain_lock:
            return self._gain

    @gain.setter
    def gain(self, value: float) -> None:
        # Clamp between 0.0 and 5.0 (0% to 500%)
        with self._gain_lock:
            self._gain = max(0.0, min(5.0, value))
        _log.debug("Gain set to %.2f", self._gain)

    @property
    def noise_suppression_enabled(self) -> bool:
        return self._noise_suppressor.enabled

    @noise_suppression_enabled.setter
    def noise_suppression_enabled(self, value: bool) -> None:
        self._noise_suppressor.enabled = value
        _log.debug("Noise suppression %s", "enabled" if value else "disabled")

    def push_audio(self, pcm: bytes) -> None:
        # Runs in packet-arrival order (single asyncio loop thread), which is
        # what the suppressor's overlap-add state requires — never call this
        # concurrently from more than one thread.
        self._packet_count += 1
        if self._packet_count % 100 == 1:
            samples = np.frombuffer(pcm, dtype=np.int16)
            rms = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2))) if len(samples) else 0.0
            _log.info("Audio packet #%d: %d bytes, input RMS=%.1f", self._packet_count, len(pcm), rms)
        processed = self._noise_suppressor.process(pcm)
        if not processed:
            return  # still filling the analysis window; nothing ready yet
        try:
            self._queue.put_nowait(processed)
        except queue.Full:
            pass  # falling behind: drop this chunk rather than build up latency

    def push_opus(self, opus_data: bytes) -> None:
        """Decode Opus frame and feed resulting PCM into the queue."""
        if self._opus_decoder is None:
            _log.debug("Opus frame received but decoder unavailable")
            return
        try:
            pcm = self._opus_decoder.decode(opus_data)
        except Exception:
            # A corrupt/hostile Opus frame raises an opuslib exception. Drop the
            # frame instead of letting it escape to asyncio and spam the log.
            _log.debug("Dropping undecodable Opus frame (%d bytes)", len(opus_data))
            return
        if pcm is not None:
            self.push_audio(pcm)

    def stop_output(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        with self._fragment_lock:
            self._fragment = b""
        self._noise_suppressor.reset()

    def _apply_gain(self, data: bytes) -> bytes:
        """Apply gain to int16 PCM data. Returns new bytes."""
        if self._gain == 1.0:
            return data
        with self._gain_lock:
            gain = self._gain
        samples = np.frombuffer(data, dtype=np.int16).astype(np.float32)
        scaled = (samples * gain).clip(-32768.0, 32767.0).astype(np.int16)
        return scaled.tobytes()

    def _audio_callback(self, outdata, frames, time_info, status):
        needed = frames * protocol.SAMPLE_WIDTH * protocol.CHANNELS
        with self._fragment_lock:
            pending = self._fragment
            while len(pending) < needed:
                try:
                    pending += self._queue.get_nowait()
                except queue.Empty:
                    break
            self._fragment, chunk = AudioBridge.reassemble(
                pending, b"", needed
            )
        # Gaps (queue underrun or a leftover tail) are silence.
        if len(chunk) < needed:
            chunk = chunk + b"\x00" * (needed - len(chunk))
        outdata[:] = self._apply_gain(chunk)

    @staticmethod
    def reassemble(existing: bytes, incoming: bytes, needed: int):
        """Pull the next fixed-size frame from the PCM backlog.

        Returns (leftover, frame) where leftover retains every byte not
        consumed by THIS frame — including any extra full frames that arrived
        in the same batch. Callers splice `leftover` back for the next callback
        so nothing is ever dropped. Testable without PortAudio.
        """
        pending = existing + incoming
        if len(pending) < needed:
            return pending, b""
        return pending[needed:], pending[:needed]

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
        self._pending_pairing: dict = {}  # addr -> {"pin": str, "device_name": str, "ts": float}
        self._pair_ttl = 60.0  # seconds a challenge stays valid before expiring

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data: bytes, addr) -> None:
        try:
            unpacked = protocol.unpack(data)
            if unpacked is None:
                return
            packet_type, payload = unpacked

            if packet_type == protocol.HELLO:
                self._handle_hello(addr, payload)
            elif packet_type == protocol.AUDIO:
                _, pcm = payload
                self._bridge.push_audio(pcm)
            elif packet_type == protocol.AUDIO_OPUS:
                _, opus_data = payload
                self._bridge.push_opus(opus_data)
            elif packet_type == protocol.BYE:
                if self._on_bye:
                    self._on_bye(addr)
            elif packet_type == protocol.PAIR_RESP:
                self._handle_pair_response(addr, payload)
            elif packet_type == protocol.PAIR_CHAL:
                # Shouldn't receive this on desktop, but handle gracefully
                _log.debug("Unexpected PAIR_CHAL from %s", addr)
        except (ValueError, TypeError, KeyError, IndexError, struct.error) as exc:
            # Includes struct.error (short AUDIO/OPUS frames) and broad runtime
            # failures from the Opus decoder on a corrupted frame. Without this
            # a single hostile datagram would escape to asyncio and spam a full
            # stack trace per packet (log-flood). The loop survives regardless;
            # we just drop cleanly instead.
            _log.debug("Dropping malformed datagram from %s: %s", addr, exc)
            return

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
                # Reply so the phone's connect handshake resolves. pack_hello has
                # no credentials, so the phone starts streaming immediately and
                # does not re-save (or reset) its stored creds.
                self.transport.sendto(protocol.pack_hello(stored_name), addr)
                return
            else:
                _log.warning("Invalid auth token from %s (%s)", name, addr[0])
                # Fall through to new device pairing

        # New/unpaired device - send pairing challenge
        pin = protocol.generate_pin()
        self._pending_pairing[addr] = {"pin": pin, "device_name": name, "ts": _time.monotonic()}
        challenge = protocol.pack_pair_challenge(pin)
        self.transport.sendto(challenge, addr)
        _log.info("Pairing challenge sent to %s (%s): PIN=%s", name, addr[0], pin)

        if self._on_pairing_request:
            self._on_pairing_request(addr, pin)

    def _handle_pair_response(self, addr, pin_payload) -> None:
        pending = self._pending_pairing.pop(addr, None)
        if not pending:
            _log.warning("PAIR_RESP from unknown addr: %s", addr)
            return

        # Reject expired challenges: the PIN shown on the desktop is only valid
        # for a short window, and cleaning up here caps memory for never-
        # answered pairing requests.
        if pending["ts"] + self._pair_ttl < _time.monotonic():
            _log.info("Expired pairing challenge from %s (%s)", pending["device_name"], addr[0])
            return

        # Require the echoed PIN to match the one we sent. Every client in this
        # codebase (mobile) echoes it, so a missing/empty payload is rejected
        # too — otherwise a bare [PAIR_RESP] byte would silently pair.
        if pin_payload != pending["pin"]:
            _log.warning(
                "PIN mismatch from %s (%s): got %r",
                pending["device_name"],
                addr[0],
                pin_payload,
            )
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