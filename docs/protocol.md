# OpenMic wire protocol (v1 draft)

Transport: a single UDP socket per connection. The desktop app binds `0.0.0.0:45820` by
default; the phone sends packets to the desktop's local WiFi IP on that port. UDP was chosen
over TCP for lower and more consistent latency — an occasional dropped audio packet is
preferable to head-of-line blocking stalling the whole stream.

## Packet format

Every packet starts with a 1-byte type tag.

| Type    | Value | Payload |
|---------|-------|---------|
| `HELLO` | 0x01  | UTF-8 device name |
| `AUDIO` | 0x02  | 4-byte big-endian sequence number + raw PCM16 mono samples |
| `BYE`   | 0x03  | (empty) |

`HELLO` is sent once when the phone connects, so the desktop app can show which device is
paired. `AUDIO` packets carry ~20ms of audio each. `BYE` is sent when the phone disconnects
cleanly (app closed, user hit disconnect).

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

## Not yet decided / open questions

- No pairing/auth: any device on the same network that knows the IP:port can stream audio.
  Fine for a local trusted network MVP, but worth revisiting before wider release.
- No reconnect/backoff logic on the phone side yet.
- No audio compression (Opus) yet — raw PCM16 at 48kHz mono is ~96 kB/s, which is fine on
  WiFi but wasteful; Opus would cut that by ~10x with negligible quality loss for voice.
