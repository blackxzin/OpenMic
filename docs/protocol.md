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
| `AUDIO`     | 0x02  | 4-byte big-endian sequence number + raw PCM16 mono samples (legacy) |
| `AUDIO_OPUS`| 0x07  | 4-byte big-endian sequence number + Opus-encoded frame |
| `BYE`       | 0x03  | (empty) |
| `PAIR_CHAL` | 0x04  | 6-digit PIN (ASCII) |
| `PAIR_RESP` | 0x05  | the same 6-digit PIN, echoed back (ASCII) |
| `PAIR_ACK`  | 0x06  | device_id (16B) + auth_token (16B) |

## Opus audio encoding

Raw PCM16 at 48 kHz mono is ~96 kB/s; Opus brings that down to ~3 kB/s at the default
setting with no audible loss for voice.

- **Sample rate**: 48 kHz
- **Channels**: 1 (mono)
- **Bitrate**: selectable on the phone — 16, 24 (default) or 48 kbps
- **Frame size**: 20 ms (960 samples per frame)
- **Application**: VoIP (optimized for voice)

The bitrate is an encoder-side setting only. An Opus frame carries its own configuration,
so the desktop decodes any of the presets without being told which one is in use — no
protocol change, no capability exchange.

`opus_dart` 3.x exposes no `OPUS_SET_BITRATE` control, so the phone enforces the preset by
sizing the encoder's output buffer per frame (`bitrate / 8 / 50` bytes for a 20 ms frame).
libopus treats that buffer as a hard ceiling and lowers quality to fit. It is a ceiling,
not a target: quiet audio still encodes smaller.

The mobile app uses `opus_flutter`/`opus_dart` to encode; the desktop uses `opuslib`
(libopus) to decode. If the phone's encoder is unavailable it falls back to raw PCM
(`AUDIO` packets), which the desktop still accepts.

## Ordering, loss and jitter

Both audio packet types carry a 32-bit sequence number, and the desktop plays frames out
in sequence order rather than arrival order:

- **Reordering**: frames are held for 3 frames (60 ms) before playout, so a packet that
  arrives after its successor still lands in its own slot.
- **Loss**: a frame that never arrives is concealed by libopus (`opus_decode` with a NULL
  packet reconstructs a plausible continuation). The legacy PCM path inserts silence of the
  same frame length instead, since there is no codec state to extrapolate from.
- **Duplicates** are dropped; a frame that arrives after its playout point is dropped too
  (playing it late would stutter and shift every later frame).
- **Resync**: a sequence jump larger than 100 frames is treated as a new stream (the phone
  reconnected and restarted its counter) rather than 100 frames of loss.

The desktop UI surfaces the resulting quality numbers live: bandwidth, loss percentage,
interarrival jitter (RFC 3550 smoothing), buffer depth and packet counters.

## Pairing flow (v1)

First-time pairing uses a PIN-based challenge to confirm both ends see the same code:

1. Phone → Desktop: `HELLO v1` (unpaired, device name only)
2. Desktop → Phone: `PAIR_CHAL` with a random 6-digit PIN
3. Phone displays the PIN; user confirms it matches the desktop's screen
4. Phone → Desktop: `PAIR_RESP`, echoing the PIN
5. Desktop verifies the echoed PIN matches the one it sent, and that the challenge has not
   expired (60 s)
6. Desktop → Phone: `PAIR_ACK` with `device_id` (16B) + `auth_token` (16B)
7. Phone stores credentials in the platform keystore; starts streaming

On subsequent connections, the phone sends a **paired `HELLO`** with stored credentials:

1. Phone → Desktop: `HELLO v1` (paired, includes `device_id` + `auth_token` + name)
2. Desktop verifies `auth_token` against its encrypted store
3. If valid → device connected, phone starts streaming immediately (no PIN)

An invalid token falls through to the pairing challenge instead of being accepted.

## Audio source authorization

Pairing authenticates `HELLO`, but audio arrives as bare datagrams on the same port. The
desktop therefore only accepts `AUDIO`/`AUDIO_OPUS` from an address that completed a
handshake — a trusted paired `HELLO` or a full pairing exchange. Anything else is dropped
and counted (logged once per 100 drops, so a flood can't spam the log).

Authorization is per source address and expires 60 s after the last packet from it, then
refreshes on every accepted packet. Phones re-bind to a new source port on each reconnect
and DHCP can move them to a new IP, so a permanent entry would keep accepting audio from
whatever host later holds that address. `BYE` revokes it immediately.

Without this check, any host on the same WiFi could inject audio into the virtual
microphone with no credentials at all.

## Credential storage

The desktop stores paired devices in `~/.config/openmic/paired_devices.enc`, encrypted with
Fernet using a key kept in the OS keyring. When no keyring backend is available it falls
back to a key derived locally — no better than plaintext against a process running as the
same user, but no worse than the JSON file it replaced.

The phone stores its `device_id`/`auth_token` in the platform keystore/keychain via
`flutter_secure_storage`.

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

Received frames pass through the jitter buffer, then the decoder, then optional noise
suppression, then a gain stage, before being written to the sink.

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

- No stereo mode. Mono is right for a microphone, but a "line in" mode for streaming music
  from the phone would need a channel count in the protocol.
- The desktop can't tell the phone that its Opus decoder is missing, so a desktop without
  libopus silently receives nothing while the phone happily streams Opus. A capability byte
  in the `HELLO` reply would fix it.
- No forward error correction. Opus supports in-band FEC, which would recover isolated
  losses better than concealment does.
- Jitter buffer depth is fixed at 3 frames. Adapting it to measured jitter would trade
  latency for robustness automatically instead of being a compile-time choice.
