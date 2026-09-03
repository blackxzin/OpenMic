"""Wire protocol shared between the mobile app and the desktop server.

Single UDP socket, one byte packet type prefix:
  HELLO       -> announces a phone connecting, payload is the device name (UTF-8)
  AUDIO_PCM   -> sequence number (4 bytes, big-endian) + raw PCM16 mono samples
  AUDIO_OPUS  -> sequence number (4 bytes, big-endian) + Opus-encoded frame
  BYE         -> phone disconnecting, no payload
  PAIR_CHAL   -> desktop -> phone: pairing challenge with PIN
  PAIR_RESP   -> phone -> desktop: user confirmed PIN
  PAIR_ACK    -> desktop -> phone: pairing confirmed, includes device_id + token

v1 HELLO format: [0x01, 0x01, device_name]
v1 HELLO (paired): [0x01, 0x01, device_id (16 bytes) + auth_token (16 bytes) + device_name]
"""

import secrets
import struct

HELLO = 0x01
AUDIO = 0x02      # raw PCM16 (legacy)
BYE = 0x03
PAIR_CHAL = 0x04
PAIR_RESP = 0x05
PAIR_ACK = 0x06
AUDIO_OPUS = 0x07  # Opus-encoded audio frame

PROTOCOL_VERSION = 0x01

SAMPLE_RATE = 48000
CHANNELS = 1
SAMPLE_WIDTH = 2  # 16-bit PCM

# Opus encoding settings
OPUS_BITRATE = 24000          # 24 kbps - voice quality, ~10x smaller than PCM
OPUS_FRAME_SIZE_MS = 20       # 20ms frames
OPUS_FRAME_SAMPLES = SAMPLE_RATE * OPUS_FRAME_SIZE_MS // 1000  # 960 samples per frame

# Selectable quality presets. Only the encoder (phone) needs to know the
# bitrate — an Opus frame carries its own configuration, so the desktop
# decoder handles any of these without being told which one is in use.
OPUS_BITRATE_MIN = 12000      # intelligible speech on a congested network
OPUS_BITRATE_MAX = 64000      # near-transparent voice, ~2.7x the default
OPUS_BITRATE_PRESETS = (16000, 24000, 48000)


def clamp_bitrate(value: int) -> int:
    """Keep a requested bitrate inside the range libopus handles for voice."""
    return max(OPUS_BITRATE_MIN, min(OPUS_BITRATE_MAX, int(value)))

DEVICE_ID_LEN = 16
AUTH_TOKEN_LEN = 16
PIN_LEN = 6  # digits

_AUDIO_HEADER = struct.Struct(">I")


def pack_hello(device_name: str) -> bytes:
    return bytes([HELLO, PROTOCOL_VERSION]) + device_name.encode("utf-8")


def pack_hello_paired(device_id: bytes, auth_token: bytes, device_name: str) -> bytes:
    """HELLO for already-paired device: version + device_id + auth_token + name."""
    return (
        bytes([HELLO, PROTOCOL_VERSION])
        + device_id
        + auth_token
        + device_name.encode("utf-8")
    )


def pack_hello_v0(device_name: str) -> bytes:
    """Pack a pre-versioning HELLO for pairing challenge (no version byte)."""
    return bytes([HELLO]) + device_name.encode("utf-8")


def pack_audio(sequence: int, pcm: bytes) -> bytes:
    return bytes([AUDIO]) + _AUDIO_HEADER.pack(sequence) + pcm


def pack_audio_opus(sequence: int, opus_data: bytes) -> bytes:
    return bytes([AUDIO_OPUS]) + _AUDIO_HEADER.pack(sequence) + opus_data


def pack_bye() -> bytes:
    return bytes([BYE])


def pack_pair_challenge(pin: str) -> bytes:
    """Desktop -> Phone: pairing challenge with PIN."""
    return bytes([PAIR_CHAL]) + pin.encode("ascii")


def pack_pair_response(pin: str) -> bytes:
    """Phone -> Desktop: user confirmed PIN, echoing it back for validation."""
    return bytes([PAIR_RESP]) + pin.encode("ascii")


def pack_pair_ack(device_id: bytes, auth_token: bytes) -> bytes:
    """Desktop -> Phone: pairing confirmed, includes device_id + auth_token."""
    return bytes([PAIR_ACK]) + device_id + auth_token


def generate_device_id() -> bytes:
    return secrets.token_bytes(DEVICE_ID_LEN)


def generate_auth_token() -> bytes:
    return secrets.token_bytes(AUTH_TOKEN_LEN)


def generate_pin() -> str:
    return "".join(str(secrets.randbelow(10)) for _ in range(PIN_LEN))


def unpack(packet: bytes):
    if not packet:
        raise ValueError("empty packet")
    packet_type = packet[0]
    if packet_type == HELLO:
        if len(packet) < 3:
            raise ValueError("HELLO packet too short for version+name")
        version = packet[1]
        if version == PROTOCOL_VERSION:
            # Check if paired HELLO (has device_id + auth_token = 32 bytes before name)
            if len(packet) >= 2 + DEVICE_ID_LEN + AUTH_TOKEN_LEN:
                device_id = packet[2 : 2 + DEVICE_ID_LEN]
                auth_token = packet[2 + DEVICE_ID_LEN : 2 + DEVICE_ID_LEN + AUTH_TOKEN_LEN]
                name = packet[2 + DEVICE_ID_LEN + AUTH_TOKEN_LEN :].decode("utf-8", errors="replace")
                return HELLO, (version, device_id, auth_token, name)
            # Regular v1 HELLO
            return HELLO, (version, None, None, packet[2:].decode("utf-8", errors="replace"))
        # Backward compat: treat as pre-versioning HELLO
        return HELLO, (0, None, None, packet[1:].decode("utf-8", errors="replace"))
    if packet_type == AUDIO:
        (sequence,) = _AUDIO_HEADER.unpack(packet[1:5])
        return AUDIO, (sequence, packet[5:])
    if packet_type == AUDIO_OPUS:
        (sequence,) = _AUDIO_HEADER.unpack(packet[1:5])
        return AUDIO_OPUS, (sequence, packet[5:])
    if packet_type == BYE:
        return BYE, None
    if packet_type == PAIR_CHAL:
        pin = packet[1:].decode("ascii", errors="replace")
        return PAIR_CHAL, pin
    if packet_type == PAIR_RESP:
        # v1: echoes the PIN as an ASCII payload for validation; v0: empty.
        pin = packet[1:].decode("ascii", errors="replace")
        return PAIR_RESP, pin
    if packet_type == PAIR_ACK:
        if len(packet) < 1 + DEVICE_ID_LEN + AUTH_TOKEN_LEN:
            raise ValueError("PAIR_ACK too short")
        device_id = packet[1 : 1 + DEVICE_ID_LEN]
        auth_token = packet[1 + DEVICE_ID_LEN : 1 + DEVICE_ID_LEN + AUTH_TOKEN_LEN]
        return PAIR_ACK, (device_id, auth_token)
    raise ValueError(f"unknown packet type: {packet_type}")
