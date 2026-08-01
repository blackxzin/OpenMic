# OpenMic wire protocol (v1)

Transport: a single UDP socket per connection. The desktop app binds `0.0.0.0:45820` by
default; the phone sends packets to the desktop's local WiFi IP on that port. UDP was chosen
over TCP for lower and more consistent latency — an occasional dropped audio packet is
preferable to head-of-line blocking stalling the whole stream.

## Packet format

Every packet starts with a 1-byte type tag.

| Type        | Value | Payload |
|-------------|-------|---------|
| `HELLO`     | 0x01  | v1 unpaired: `[0x01 0x01] + UTF-8 device name`<br>v1 paired: `[0x01 0x01] + device_id (16B) + auth_token (16B) + UTF-8 device name`<br>v0: UTF-8 device name (no version) |
| `AUDIO`     | 0x02  | 4-byte big-endian sequence number + raw PCM16 mono samples |
| `BYE`       | 0x03  | (empty) |
| `PAIR_CHAL` | 0x04  | 6-digit PIN (ASCII) |
| `PAIR_RESP` | 0x05  | (empty) |
| `PAIR_ACK`  | 0x06  | device_id (16B) + auth_token (16B) |

## Pairing flow (v1)

First-time pairing uses a PIN-based challenge to confirm both ends see the same code:

1. Phone → Desktop: `HELLO v1` (unpaired, device name only)
2. Desktop → Phone: `PAIR_CHAL` with a random 6-digit PIN
3. Phone displays the PIN; user confirms it matches the desktop's screen
4. Phone → Desktop: `PAIR_RESP`
5. Desktop → Phone: `PAIR_ACK` with `device_id` (16B) + `auth_token` (16B)
6. Phone stores credentials; starts streaming `AUDIO`

On subsequent connections, the phone sends a **paired `HELLO`** with stored credentials:

1. Phone → Desktop: `HELLO v1` (paired, includes `device_id` + `auth_token` + name)
2. Desktop verifies `auth_token` against `~/.config/openmic/paired_devices.json`
3. If valid → device connected, phone starts streaming immediately (no PIN)

This prevents unauthorized devices on the same network from streaming audio. The desktop
stores paired devices in `~/.config/openmic/paired_devices.json`.

## Audio format

- Sample rate: 48000 Hz
- Channels: 1 (mono)
- Sample format: signed 16-bit PCM, little-endian in memory (network byte order only applies
  to the sequence number header, not the PCM payload)

## Desktop side

The desktop app creates a virtual microphone via PipeWire's PulseAudio compatibility layer:

1. `module-null-sink` named `OpenMicSink` — the app writes decoded PCM into this sink.
2. `module-remap-source` named `OpenMic_Microphone`, mastered from `OpenMicSink.monitor` —
   this is what shows up as a selectable microphone in other apps (Discord, browser, etc).

## Backward compatibility

`unpack()` detects pre-versioning HELLO by checking if the byte after `0x01` equals
`PROTOCOL_VERSION (0x01)`. If not, it's treated as v0 (name starts at index 1).

For paired HELLO detection: if the packet has ≥34 bytes after the version byte
(16B device_id + 16B auth_token + name), it's a paired HELLO.

## Reconnect

The mobile app implements exponential backoff reconnection (1s → 2s → 4s → 8s → 16s, capped at 30s)
with a maximum of 5 attempts. User-initiated disconnects cancel reconnection. Credentials from
a successful pairing are reused automatically on reconnect.

## Not yet decided / open questions

- No audio compression (Opus) yet — raw PCM16 at 48kHz mono is ~96 kB/s, which is fine on
  WiFi but wasteful; Opus would cut that by ~10x with negligible quality loss for voice.
- No way to view/unpair devices from the desktop UI yet (only the mobile app can unpair).
- Pairing credentials are stored unencrypted; for higher security, could use OS keychain.