"""Wire protocol shared between the mobile app and the desktop server.

Single UDP socket, one byte packet type prefix:
  HELLO  -> announces a phone connecting, payload is the device name (UTF-8)
  AUDIO  -> sequence number (4 bytes, big-endian) + raw PCM16 mono samples
  BYE    -> phone disconnecting, no payload
"""

import struct

HELLO = 0x01
AUDIO = 0x02
BYE = 0x03

SAMPLE_RATE = 48000
CHANNELS = 1
SAMPLE_WIDTH = 2  # 16-bit PCM

_AUDIO_HEADER = struct.Struct(">I")


def pack_hello(device_name: str) -> bytes:
    return bytes([HELLO]) + device_name.encode("utf-8")


def pack_audio(sequence: int, pcm: bytes) -> bytes:
    return bytes([AUDIO]) + _AUDIO_HEADER.pack(sequence) + pcm


def pack_bye() -> bytes:
    return bytes([BYE])


def unpack(packet: bytes):
    if not packet:
        raise ValueError("empty packet")
    packet_type = packet[0]
    if packet_type == HELLO:
        return HELLO, packet[1:].decode("utf-8", errors="replace")
    if packet_type == AUDIO:
        (sequence,) = _AUDIO_HEADER.unpack(packet[1:5])
        return AUDIO, (sequence, packet[5:])
    if packet_type == BYE:
        return BYE, None
    raise ValueError(f"unknown packet type: {packet_type}")
