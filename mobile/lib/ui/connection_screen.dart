import 'dart:async';
import 'dart:io';
import 'dart:typed_data';

import 'package:bonsoir/bonsoir.dart';
import 'package:flutter/material.dart';
import 'package:opus_dart/opus_dart.dart';
import 'package:opus_flutter/opus_flutter.dart' as opus_flutter;
import 'package:record/record.dart';

import '../audio/opus_framer.dart';
import '../audio/vu_level.dart';
import '../l10n/strings.dart';
import '../models/connection_status.dart';
import '../native/platform_hooks.dart';
import '../protocol.dart';
import '../storage/credentials_store.dart';
import '../storage/settings_store.dart';
import 'connection_body.dart';
import 'quality_selector.dart';

const String serviceType = '_openmic._udp';

class ConnectionScreen extends StatefulWidget {
  const ConnectionScreen({super.key});

  @override
  State<ConnectionScreen> createState() => _ConnectionScreenState();
}

class _ConnectionScreenState extends State<ConnectionScreen> {
  final TextEditingController _ipController = TextEditingController();
  final TextEditingController _portController = TextEditingController(text: '45820');
  final AudioRecorder _recorder = AudioRecorder();
  final CredentialsStore _credentialsStore = const CredentialsStore();
  final SettingsStore _settingsStore = SettingsStore();

  RawDatagramSocket? _socket;
  // Set up once per socket and never cancelled until the socket itself
  // closes — repeatedly cancelling/re-listening on a RawDatagramSocket
  // between the HELLO/CHAL and PAIR_RESP/ACK steps was observed to leave the
  // socket permanently unable to send afterwards (send() returns 0 forever,
  // Wifi-radio-sleep and buffer-backpressure theories both ruled out on
  // device). One persistent listener dispatching into a swappable completer
  // avoids ever tearing down the socket's read/write registration mid-flow.
  StreamSubscription<RawSocketEvent>? _socketSubscription;
  Completer<Datagram?>? _pendingResponse;
  StreamSubscription<Uint8List>? _audioSubscription;
  InternetAddress? _serverAddress;
  int _serverPort = 45820;
  int _sequence = 0;

  ConnectionStatus _status = ConnectionStatus.disconnected;
  String? _errorMessage;

  // Reconnect state
  int _reconnectAttempt = 0;
  static const int _maxReconnectAttempts = 5;
  static const Duration _baseReconnectDelay = Duration(seconds: 1);
  Timer? _reconnectTimer;
  bool _userInitiatedDisconnect = false;

  DeviceCredentials? _credentials;

  SimpleOpusEncoder? _opusEncoder;
  final OpusFramer _framer = OpusFramer();
  int _bitrate = Protocol.opusBitrate;

  final VuLevelTracker _vuTracker = VuLevelTracker();
  double _vuLevel = 0.0;
  Timer? _vuUpdateTimer;

  BonsoirDiscovery? _discovery;
  StreamSubscription<BonsoirDiscoveryEvent>? _discoverySubscription;
  final Map<String, BonsoirService> _foundDevices = <String, BonsoirService>{};

  @override
  void initState() {
    super.initState();
    _startDiscovery();
    _loadStoredCredentials();
    _loadBitrate();
    _initOpusEncoder();
  }

  @override
  void dispose() {
    _disconnect();
    unawaited(releaseWifiLock());
    unawaited(stopForegroundService());
    _discoverySubscription?.cancel();
    _discovery?.stop();
    _ipController.dispose();
    _portController.dispose();
    _recorder.dispose();
    _opusEncoder?.destroy();
    _vuUpdateTimer?.cancel();
    super.dispose();
  }

  // ------------------------------------------------------------- discovery

  Future<void> _startDiscovery() async {
    try {
      await _startDiscoveryUnguarded();
    } catch (error) {
      // mDNS is a convenience: without it the manual IP field still works,
      // so a platform that refuses to browse must not break the screen.
      _logDebug('Discovery unavailable: $error');
    }
  }

  Future<void> _startDiscoveryUnguarded() async {
    final BonsoirDiscovery discovery = BonsoirDiscovery(type: serviceType);
    _discovery = discovery;
    await discovery.initialize();
    _discoverySubscription = discovery.eventStream?.listen((BonsoirDiscoveryEvent event) {
      if (event is BonsoirDiscoveryServiceFoundEvent) {
        event.service.resolve(discovery.serviceResolver);
      } else if (event is BonsoirDiscoveryServiceResolvedEvent) {
        final BonsoirService svc = event.service;
        setState(() => _foundDevices[svc.name] = svc);
      } else if (event is BonsoirDiscoveryServiceLostEvent) {
        final BonsoirService svc = event.service;
        setState(() => _foundDevices.remove(svc.name));
      }
    });
    await discovery.start();
  }

  void _connectToDiscovered(BonsoirService service) {
    final String? host = service.hostAddress;
    if (host == null) return;
    _ipController.text = host;
    _portController.text = service.port.toString();
    _connect();
  }

  // ------------------------------------------------------------- settings

  Future<void> _loadStoredCredentials() async {
    DeviceCredentials? stored;
    try {
      stored = await _credentialsStore.load();
    } catch (error) {
      // An unreadable keystore means "not paired yet", not a dead app: the
      // user can pair again and overwrite whatever is in there.
      _logDebug('Could not read stored credentials: $error');
      return;
    }
    if (stored == null || !mounted) return;
    setState(() => _credentials = stored);
  }

  Future<void> _saveCredentials(DeviceCredentials credentials) async {
    await _credentialsStore.save(credentials);
    if (!mounted) {
      _credentials = credentials;
      return;
    }
    setState(() => _credentials = credentials);
  }

  Future<void> _loadBitrate() async {
    int stored;
    try {
      stored = await _settingsStore.loadBitrate();
    } catch (error) {
      _logDebug('Could not read the stored quality setting: $error');
      return;  // keep the default preset
    }
    if (!mounted) return;
    setState(() => _bitrate = QualitySelector.snapToPreset(stored));
  }

  Future<void> _onBitrateChanged(int bitrate) async {
    setState(() => _bitrate = bitrate);
    try {
      await _settingsStore.saveBitrate(bitrate);
    } catch (error) {
      // The choice still applies to this session; it just won't be
      // remembered next launch.
      _logDebug('Could not persist the quality setting: $error');
    }
  }

  Future<void> _initOpusEncoder() async {
    try {
      // No static type here: opus_flutter.load() returns Future<dynamic>
      // because its actual DynamicLibrary type (dart:ffi vs web_ffi) is
      // resolved per-platform inside opus_dart's own conditional export —
      // annotating it dart:ffi's DynamicLibrary here fights that resolution.
      final lib = await opus_flutter.load();
      initOpus(lib);
      _opusEncoder = SimpleOpusEncoder(
        sampleRate: Protocol.sampleRate,
        channels: Protocol.channels,
        application: Application.voip,
      );
    } catch (e) {
      _logDebug('Opus encoder unavailable: $e');
    }
  }

  void _logDebug(String msg) {
    debugPrint('[OpenMic] $msg');
  }

  // ---------------------------------------------------------------- socket

  /// RawDatagramSocket.send() can write 0 bytes instead of throwing when the
  /// OS isn't ready to accept the write. Note: this must NOT attach its own
  /// listener to retry via RawSocketEvent.write — [_socket] carries exactly
  /// one persistent listener ([_socketSubscription]) for its whole lifetime
  /// now, and RawDatagramSocket only allows a single subscription ever. A
  /// plain delayed retry avoids that conflict.
  Future<void> _sendReliable(Uint8List data, InternetAddress address, int port) async {
    final DateTime deadline = DateTime.now().add(const Duration(seconds: 10));
    while (true) {
      final int sent = _socket!.send(data, address, port);
      if (sent == data.length) return;
      if (DateTime.now().isAfter(deadline)) {
        _logDebug('send() gave up after 10s of retrying');
        throw const SocketException('send() kept writing 0 bytes past the retry deadline');
      }
      _logDebug('send() wrote $sent/${data.length} bytes, retrying');
      await Future<void>.delayed(const Duration(milliseconds: 150));
    }
  }

  Future<void> _connect() async {
    final String ip = _ipController.text.trim();
    final int? port = int.tryParse(_portController.text.trim());
    if (ip.isEmpty || port == null) {
      setState(() {
        _status = ConnectionStatus.error;
        _errorMessage = Strings.tr('invalid_address');
      });
      return;
    }
    // A fresh connect attempt is never user-cancelled, so auto-reconnect is
    // allowed again.
    _userInitiatedDisconnect = false;
    await acquireWifiLock();
    await startForegroundService();

    setState(() {
      _status = ConnectionStatus.connecting;
      _errorMessage = null;
    });

    if (!await _recorder.hasPermission()) {
      setState(() {
        _status = ConnectionStatus.error;
        _errorMessage = Strings.tr('mic_permission_denied');
      });
      return;
    }

    try {
      _serverAddress = InternetAddress(ip);
      _serverPort = port;
      // Never leak a prior bind: if a previous attempt's socket wasn't torn
      // down (e.g. a race between a reconnect timer and a manual connect),
      // close it before binding a fresh one.
      await _socketSubscription?.cancel();
      _socket?.close();
      _socket = await RawDatagramSocket.bind(InternetAddress.anyIPv4, 0);
      _socketSubscription = _socket!.listen((RawSocketEvent event) {
        if (event == RawSocketEvent.read) {
          final Datagram? d = _socket!.receive();
          if (d != null && _pendingResponse != null && !_pendingResponse!.isCompleted) {
            _pendingResponse!.complete(d);
          }
        }
      });

      // Send HELLO - paired or unpaired
      final DeviceCredentials? credentials = _credentials;
      final Uint8List helloPacket = credentials != null
          ? Protocol.packHelloPaired(
              credentials.deviceId, credentials.authToken, _deviceName())
          : Protocol.packHello(_deviceName());
      await _sendReliable(helloPacket, _serverAddress!, _serverPort);

      // Wait for response (challenge, ack, or pairing challenge)
      final Datagram? response = await _awaitResponse();
      if (response == null) {
        throw Exception(Strings.tr('server_no_reply'));
      }

      final parsed = Protocol.unpack(response.data);
      if (parsed == null) {
        throw Exception(Strings.tr('invalid_response'));
      }

      final int responseType = parsed['type'] as int;
      if (responseType == Protocol.pairChal) {
        // Pairing challenge received - show PIN to user
        await _showPairingDialog(parsed['pin'] as String);
        return; // Will continue after user confirms
      } else if (responseType == Protocol.pairAck) {
        // Pairing confirmed - save credentials and start streaming
        await _saveCredentials(DeviceCredentials(
          deviceId: parsed['deviceId'] as Uint8List,
          authToken: parsed['authToken'] as Uint8List,
        ));
        _startStreaming();
        return;
      } else if (responseType == Protocol.hello) {
        // Legacy or paired response without pairing flow
        if (parsed['version'] as int == Protocol.version &&
            parsed['deviceId'] != null &&
            parsed['authToken'] != null) {
          await _saveCredentials(DeviceCredentials(
            deviceId: parsed['deviceId'] as Uint8List,
            authToken: parsed['authToken'] as Uint8List,
          ));
        }
        _startStreaming();
        return;
      }

      throw Exception(Strings.tr('unexpected_response', <String, Object?>{'type': responseType}));
    } catch (error) {
      setState(() {
        _status = ConnectionStatus.error;
        _errorMessage = error.toString();
      });
      await _disconnect();
      // Schedule reconnect if not user-initiated
      if (!_userInitiatedDisconnect) {
        _scheduleReconnect();
      }
    }
  }

  Future<Datagram?> _awaitResponse() {
    final Completer<Datagram?> completer = Completer<Datagram?>();
    _pendingResponse = completer;
    return completer.future.timeout(
      const Duration(seconds: 5),
      onTimeout: () {
        if (!completer.isCompleted) completer.complete(null);
        return null;
      },
    );
  }

  Future<void> _showPairingDialog(String pin) async {
    setState(() {
      _status = ConnectionStatus.pairing;
    });

    final bool? confirmed = await showDialog<bool>(
      context: context,
      barrierDismissible: false,
      builder: (BuildContext context) => AlertDialog(
        title: Text(Strings.tr('pair_dialog_title')),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            Text(Strings.tr('pair_dialog_body')),
            const SizedBox(height: 16),
            Text(
              pin,
              style: const TextStyle(
                fontSize: 48,
                fontWeight: FontWeight.bold,
                letterSpacing: 8,
                fontFamily: 'monospace',
              ),
            ),
          ],
        ),
        actions: <Widget>[
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: Text(Strings.tr('cancel')),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: Text(Strings.tr('confirm')),
          ),
        ],
      ),
    );

    if (confirmed != true) {
      // User cancelled pairing
      await _disconnect();
      setState(() {
        _status = ConnectionStatus.disconnected;
      });
      return;
    }

    // Send PAIR_RESP, echoing the PIN so the desktop can verify the user
    // really entered the same code on the phone.
    await _sendReliable(Protocol.packPairResponse(pin), _serverAddress!, _serverPort);

    final Datagram? ack = await _awaitResponse();
    if (ack == null) {
      _logDebug('PAIR_ACK wait timed out — no response from server');
    } else {
      final parsed = Protocol.unpack(ack.data);
      if (parsed != null && parsed['type'] == Protocol.pairAck) {
        await _saveCredentials(DeviceCredentials(
          deviceId: parsed['deviceId'] as Uint8List,
          authToken: parsed['authToken'] as Uint8List,
        ));
        _startStreaming();
        return;
      }
      _logDebug('PAIR_ACK response did not parse as expected: $parsed');
    }
    throw Exception(Strings.tr('pair_failed'));
  }

  // -------------------------------------------------------------- streaming

  void _startStreaming() {
    _sequence = 0;
    _reconnectAttempt = 0;
    _reconnectTimer?.cancel();
    _reconnectTimer = null;
    _framer.clear();

    final bool useOpus = _opusEncoder != null;
    if (!useOpus) _logDebug('Opus encoder not available, falling back to PCM');

    final Future<Stream<Uint8List>> audioStream = _recorder.startStream(
      const RecordConfig(
        encoder: AudioEncoder.pcm16bits,
        sampleRate: Protocol.sampleRate,
        numChannels: Protocol.channels,
        // Best-effort: uses the platform's native noise suppressor (Android
        // NoiseSuppressor effect / iOS voice processing) when the device
        // supports it. No-op otherwise — never throws.
        noiseSuppress: true,
      ),
    );
    audioStream.then((Stream<Uint8List> stream) {
      if (mounted) {
        _audioSubscription = stream.listen(useOpus ? _onAudioChunkOpus : _onAudioChunk);
        setState(() {
          _status = ConnectionStatus.streaming;
        });
      }
    }).catchError((Object error) {
      if (mounted) {
        setState(() {
          _status = ConnectionStatus.error;
          _errorMessage = error.toString();
        });
        _disconnect();
        if (!_userInitiatedDisconnect) {
          _scheduleReconnect();
        }
      }
    });
  }

  void _onAudioChunkOpus(Uint8List pcmChunk) {
    final RawDatagramSocket? socket = _socket;
    final InternetAddress? address = _serverAddress;
    final SimpleOpusEncoder? encoder = _opusEncoder;
    if (socket == null || address == null || encoder == null) return;

    _updateVuLevel(pcmChunk);

    final int maxFrameBytes = Protocol.maxFrameBytesFor(_bitrate);
    final List<Uint8List> frames = _framer.addChunk(
      pcmChunk,
      (Int16List frame) => encoder.encode(input: frame, maxOutputSizeBytes: maxFrameBytes),
    );
    for (final Uint8List frame in frames) {
      try {
        socket.send(Protocol.packAudioOpus(_sequence, frame), address, _serverPort);
        _sequence = (_sequence + 1) & 0xFFFFFFFF;
      } on SocketException {
        // Network lost — trigger reconnect. Codec errors must NOT take this
        // path: they're transient and the socket is still healthy.
        if (!_userInitiatedDisconnect && _status == ConnectionStatus.streaming) {
          _handleConnectionLost();
        }
        return;
      }
    }
  }

  void _onAudioChunk(Uint8List chunk) {
    final RawDatagramSocket? socket = _socket;
    final InternetAddress? address = _serverAddress;
    if (socket == null || address == null) return;

    _updateVuLevel(chunk);

    try {
      socket.send(Protocol.packAudio(_sequence, chunk), address, _serverPort);
      _sequence = (_sequence + 1) & 0xFFFFFFFF;
    } on SocketException {
      // Socket error (e.g., network lost) — trigger reconnect
      if (!_userInitiatedDisconnect && _status == ConnectionStatus.streaming) {
        _handleConnectionLost();
      }
    }
  }

  void _updateVuLevel(Uint8List pcmChunk) {
    final double level = _vuTracker.add(pcmChunk);
    // Repaint at ~30fps, not once per audio chunk.
    if (_vuUpdateTimer?.isActive ?? false) return;
    _vuUpdateTimer = Timer(const Duration(milliseconds: 33), () {
      if (mounted) {
        setState(() {
          _vuLevel = level;
        });
      }
    });
  }

  // ------------------------------------------------------------- reconnect

  Future<void> _handleConnectionLost() async {
    await _disconnect();
    if (!_userInitiatedDisconnect) {
      _scheduleReconnect();
    }
  }

  void _scheduleReconnect() {
    if (_reconnectAttempt >= _maxReconnectAttempts) {
      setState(() {
        _status = ConnectionStatus.error;
        _errorMessage = Strings.tr('reconnect_gave_up');
      });
      unawaited(releaseWifiLock());
      unawaited(stopForegroundService());
      return;
    }

    _reconnectAttempt++;
    final Duration delay = _baseReconnectDelay * (1 << (_reconnectAttempt - 1));
    final Duration cappedDelay =
        delay > const Duration(seconds: 30) ? const Duration(seconds: 30) : delay;

    setState(() {
      _status = ConnectionStatus.reconnecting;
      _errorMessage = Strings.tr('reconnecting_attempt', <String, Object?>{
        'attempt': _reconnectAttempt,
        'max': _maxReconnectAttempts,
      });
    });

    _reconnectTimer?.cancel();
    _reconnectTimer = Timer(cappedDelay, () {
      if (mounted && !_userInitiatedDisconnect) {
        _connect();
      }
    });
  }

  /// Pure teardown: stop the recorder + socket and reset state. Does NOT touch
  /// [_userInitiatedDisconnect] or the reconnect timer — that's the caller's
  /// job, because this runs on both user-initiated disconnects and the
  /// internal reconnect path.
  Future<void> _disconnect() async {
    await _audioSubscription?.cancel();
    _audioSubscription = null;
    _framer.clear();
    _vuTracker.reset();

    if (await _recorder.isRecording()) {
      await _recorder.stop();
    }

    if (_socket != null && _serverAddress != null) {
      _socket!.send(Protocol.packBye(), _serverAddress!, _serverPort);
    }
    await _socketSubscription?.cancel();
    _socketSubscription = null;
    _socket?.close();
    _socket = null;
    _serverAddress = null;
    _pendingResponse = null;

    if (mounted) {
      setState(() {
        _status = ConnectionStatus.disconnected;
        _vuLevel = 0.0;
      });
    }
  }

  /// Disconnect because the user asked: block auto-reconnect.
  Future<void> _disconnectByUser() async {
    _userInitiatedDisconnect = true;
    _reconnectTimer?.cancel();
    _reconnectTimer = null;
    _reconnectAttempt = 0;
    await _disconnect();
    await releaseWifiLock();
    await stopForegroundService();
  }

  String _deviceName() => Platform.isIOS ? 'iPhone' : 'Android';

  // ------------------------------------------------------------------- view

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('OpenMic'),
        actions: <Widget>[
          if (_credentials != null)
            PopupMenuButton<String>(
              onSelected: (String value) {
                if (value == 'unpair') {
                  _showUnpairDialog();
                }
              },
              itemBuilder: (BuildContext context) => <PopupMenuEntry<String>>[
                PopupMenuItem<String>(
                  value: 'unpair',
                  child: Text(Strings.tr('unpair_menu')),
                ),
              ],
            ),
        ],
      ),
      body: ConnectionBody(
        foundDevices: _foundDevices.values,
        ipController: _ipController,
        portController: _portController,
        status: _status,
        errorMessage: _errorMessage,
        bitrate: _bitrate,
        vuLevel: _vuLevel,
        onConnectDiscovered: _connectToDiscovered,
        onPrimaryAction: _status == ConnectionStatus.streaming ? _disconnectByUser : _connect,
        onBitrateChanged: _onBitrateChanged,
      ),
    );
  }

  Future<void> _showUnpairDialog() async {
    final bool? confirmed = await showDialog<bool>(
      context: context,
      builder: (BuildContext context) => AlertDialog(
        title: Text(Strings.tr('unpair_title')),
        content: Text(Strings.tr('unpair_body')),
        actions: <Widget>[
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: Text(Strings.tr('cancel')),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: Text(Strings.tr('unpair_title')),
          ),
        ],
      ),
    );
    if (confirmed == true) {
      await _credentialsStore.clear();
      if (!mounted) return;
      setState(() => _credentials = null);
    }
  }
}
