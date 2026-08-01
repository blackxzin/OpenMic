import 'dart:async';
import 'dart:io';
import 'dart:typed_data';

import 'package:bonsoir/bonsoir.dart';
import 'package:flutter/material.dart';
import 'package:opus_flutter/opus_flutter.dart';
import 'package:record/record.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'protocol.dart';

const _serviceType = '_openmic._udp';

void main() {
  runApp(const OpenMicApp());
}

class OpenMicApp extends StatelessWidget {
  const OpenMicApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'OpenMic',
      theme: ThemeData(colorSchemeSeed: Colors.teal, useMaterial3: true),
      home: const ConnectionScreen(),
    );
  }
}

enum ConnectionStatus { disconnected, connecting, pairing, streaming, reconnecting, error }

class ConnectionScreen extends StatefulWidget {
  const ConnectionScreen({super.key});

  @override
  State<ConnectionScreen> createState() => _ConnectionScreenState();
}

class _ConnectionScreenState extends State<ConnectionScreen> {
  final _ipController = TextEditingController();
  final _portController = TextEditingController(text: '45820');
  final _recorder = AudioRecorder();

  RawDatagramSocket? _socket;
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

  // Pairing state
  String? _pendingPin;
  Uint8List? _deviceId;
  Uint8List? _authToken;
  bool _showPairingDialog = false;

  // Opus encoder
  OpusFlutter? _opusEncoder;

  BonsoirDiscovery? _discovery;
  StreamSubscription<BonsoirDiscoveryEvent>? _discoverySubscription;
  final Map<String, BonsoirService> _foundDevices = {};

  @override
  void initState() {
    super.initState();
    _startDiscovery();
    _loadStoredCredentials();
    _initOpusEncoder();
  }

  Future<void> _startDiscovery() async {
    final discovery = BonsoirDiscovery(type: _serviceType);
    _discovery = discovery;
    await discovery.initialize();
    _discoverySubscription = discovery.eventStream?.listen((event) {
      switch (event) {
        case BonsoirDiscoveryServiceFoundEvent():
          event.service.resolve(discovery.serviceResolver);
        case BonsoirDiscoveryServiceResolvedEvent():
          setState(() => _foundDevices[event.service.name] = event.service);
        case BonsoirDiscoveryServiceLostEvent():
          setState(() => _foundDevices.remove(event.service.name));
        default:
          break;
      }
    });
    await discovery.start();
  }

  void _connectToDiscovered(BonsoirService service) {
    final host = service.hostAddress;
    if (host == null) return;
    _ipController.text = host;
    _portController.text = service.port.toString();
    _connect();
  }

  @override
  void dispose() {
    _disconnect();
    _discoverySubscription?.cancel();
    _discovery?.stop();
    _ipController.dispose();
    _portController.dispose();
    _recorder.dispose();
    _opusEncoder?.close();
    super.dispose();
  }

  Future<void> _initOpusEncoder() async {
    try {
      _opusEncoder = await OpusFlutter.create(
        sampleRate: Protocol.sampleRate,
        channels: Protocol.channels,
        bitrate: Protocol.opusBitrate,
        frameSize: Protocol.opusFrameSamples,
      );
      _opusEncoder?.setBitrate(Protocol.opusBitrate);
    } catch (e) {
      _logDebug('Opus encoder unavailable: $e');
    }
  }

  void _logDebug(String msg) {
    debugPrint('[OpenMic] $msg');
  }

  Future<void> _loadStoredCredentials() async {
    final prefs = await SharedPreferences.getInstance();
    final deviceIdHex = prefs.getString('device_id');
    final authTokenHex = prefs.getString('auth_token');
    if (deviceIdHex != null && authTokenHex != null) {
      _deviceId = Uint8List.fromList(deviceIdHex.split('').map((c) => int.parse(c, radix: 16)).toList());
      _authToken = Uint8List.fromList(authTokenHex.split('').map((c) => int.parse(c, radix: 16)).toList());
    }
  }

  Future<void> _saveCredentials(Uint8List deviceId, Uint8List authToken) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('device_id', deviceId.map((b) => b.toRadixString(16).padLeft(2, '0')).join());
    await prefs.setString('auth_token', authToken.map((b) => b.toRadixString(16).padLeft(2, '0')).join());
    _deviceId = deviceId;
    _authToken = authToken;
  }

  Future<void> _clearCredentials() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove('device_id');
    await prefs.remove('auth_token');
    _deviceId = null;
    _authToken = null;
  }

  Future<void> _connect() async {
    final ip = _ipController.text.trim();
    final port = int.tryParse(_portController.text.trim());
    if (ip.isEmpty || port == null) {
      setState(() {
        _status = ConnectionStatus.error;
        _errorMessage = 'Informe um IP e porta válidos';
      });
      return;
    }

    setState(() {
      _status = ConnectionStatus.connecting;
      _errorMessage = null;
    });

    if (!await _recorder.hasPermission()) {
      setState(() {
        _status = ConnectionStatus.error;
        _errorMessage = 'Permissão de microfone negada';
      });
      return;
    }

    try {
      _serverAddress = InternetAddress(ip);
      _serverPort = port;
      _socket = await RawDatagramSocket.bind(InternetAddress.anyIPv4, 0);

      // Send HELLO - paired or unpaired
      Uint8List helloPacket;
      if (_deviceId != null && _authToken != null) {
        helloPacket = Protocol.packHelloPaired(_deviceId!, _authToken!, _deviceName());
      } else {
        helloPacket = Protocol.packHello(_deviceName());
      }
      _socket!.send(helloPacket, _serverAddress!, _serverPort);

      // Wait for response (challenge, ack, or pairing challenge)
      final completer = Completer<Datagram?>();
      late final StreamSubscription<RawSocketEvent> sub;
      sub = _socket!.listen((event) {
        if (event == RawSocketEvent.read) {
          final d = _socket!.receive();
          if (d != null && !completer.isCompleted) {
            completer.complete(d);
          }
        }
      });

      final response = await completer.future.timeout(
        const Duration(seconds: 5),
        onTimeout: () {
          if (!completer.isCompleted) completer.complete(null);
        },
      );

      await sub.cancel();

      if (response == null) {
        throw Exception('Servidor não respondeu — verifique o IP e porta');
      }

      final parsed = Protocol.unpack(response.data);
      if (parsed == null) {
        throw Exception('Resposta inválida do servidor');
      }

      // Handle different response types
      final responseType = parsed['type'] as int;
      if (responseType == Protocol.pairChal) {
        // Pairing challenge received - show PIN to user
        final pin = parsed['pin'] as String;
        await _showPairingDialog(pin);
        return; // Will continue after user confirms
      } else if (responseType == Protocol.pairAck) {
        // Pairing confirmed - save credentials and start streaming
        final deviceId = parsed['deviceId'] as Uint8List;
        final authToken = parsed['authToken'] as Uint8List;
        await _saveCredentials(deviceId, authToken);
        _startStreaming();
        return;
      } else if (responseType == Protocol.hello) {
        // Legacy or paired response without pairing flow
        final version = parsed['version'] as int;
        if (version == Protocol.version) {
          // Check if it's a paired response (has deviceId/authToken)
          if (parsed['deviceId'] != null && parsed['authToken'] != null) {
            await _saveCredentials(
              parsed['deviceId'] as Uint8List,
              parsed['authToken'] as Uint8List,
            );
          }
        }
        _startStreaming();
        return;
      }

      throw Exception('Resposta inesperada do servidor: $responseType');
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

  Future<void> _showPairingDialog(String pin) async {
    setState(() {
      _pendingPin = pin;
      _status = ConnectionStatus.pairing;
    });

    // Show dialog and wait for user confirmation
    final confirmed = await showDialog<bool>(
      context: context,
      barrierDismissible: false,
      builder: (context) => AlertDialog(
        title: const Text('Emparelhar dispositivo'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text('Confirme o PIN no computador:'),
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
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('Cancelar'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text('Confirmar'),
          ),
        ],
      ),
    );

    if (confirmed == true) {
      // Send PAIR_RESP
      _socket!.send(Protocol.packPairResponse(), _serverAddress!, _serverPort);

      // Wait for PAIR_ACK
      final completer = Completer<Datagram?>();
      late final StreamSubscription<RawSocketEvent> sub;
      sub = _socket!.listen((event) {
        if (event == RawSocketEvent.read) {
          final d = _socket!.receive();
          if (d != null && !completer.isCompleted) {
            completer.complete(d);
          }
        }
      });

      final ack = await completer.future.timeout(
        const Duration(seconds: 5),
        onTimeout: () {
          if (!completer.isCompleted) completer.complete(null);
        },
      );

      await sub.cancel();

      if (ack != null) {
        final parsed = Protocol.unpack(ack.data);
        if (parsed != null && parsed['type'] == Protocol.pairAck) {
          final deviceId = parsed['deviceId'] as Uint8List;
          final authToken = parsed['authToken'] as Uint8List;
          await _saveCredentials(deviceId, authToken);
          _startStreaming();
          return;
        }
      }
      throw Exception('Falha ao confirmar emparelhamento');
    } else {
      // User cancelled pairing
      await _disconnect();
      setState(() {
        _status = ConnectionStatus.disconnected;
      });
    }
  }

  void _startStreaming() {
    _sequence = 0;
    _reconnectAttempt = 0;
    _reconnectTimer?.cancel();
    _reconnectTimer = null;

    if (_opusEncoder == null) {
      _logDebug('Opus encoder not available, falling back to PCM');
      _startPcmStreaming();
      return;
    }

    final audioStream = _recorder.startStream(
      const RecordConfig(
        encoder: AudioEncoder.pcm16bits,
        sampleRate: Protocol.sampleRate,
        numChannels: Protocol.channels,
      ),
    );
    audioStream.then((stream) {
      if (mounted) {
        _audioSubscription = stream.listen(_onAudioChunkOpus);
        setState(() {
          _status = ConnectionStatus.streaming;
        });
      }
    }).catchError((error) {
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

  void _startPcmStreaming() {
    final audioStream = _recorder.startStream(
      const RecordConfig(
        encoder: AudioEncoder.pcm16bits,
        sampleRate: Protocol.sampleRate,
        numChannels: Protocol.channels,
      ),
    );
    audioStream.then((stream) {
      if (mounted) {
        _audioSubscription = stream.listen(_onAudioChunk);
        setState(() {
          _status = ConnectionStatus.streaming;
        });
      }
    }).catchError((error) {
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
    final socket = _socket;
    final address = _serverAddress;
    if (socket == null || address == null) return;

    try {
      // Encode PCM to Opus
      final opusData = _opusEncoder!.encode(pcmChunk);
      if (opusData != null) {
        socket.send(Protocol.packAudioOpus(_sequence, opusData), address, _serverPort);
        _sequence = (_sequence + 1) & 0xFFFFFFFF;
      }
    } catch (e) {
      // Socket error (e.g., network lost) — trigger reconnect
      if (!_userInitiatedDisconnect && _status == ConnectionStatus.streaming) {
        _handleConnectionLost();
      }
    }
  }

  void _onAudioChunk(Uint8List chunk) {
    final socket = _socket;
    final address = _serverAddress;
    if (socket == null || address == null) return;
    try {
      socket.send(Protocol.packAudio(_sequence, chunk), address, _serverPort);
      _sequence = (_sequence + 1) & 0xFFFFFFFF;
    } catch (e) {
      // Socket error (e.g., network lost) — trigger reconnect
      if (!_userInitiatedDisconnect && _status == ConnectionStatus.streaming) {
        _handleConnectionLost();
      }
    }
  }

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
        _errorMessage = 'Máximo de tentativas de reconexão atingido';
      });
      return;
    }

    _reconnectAttempt++;
    final delay = _baseReconnectDelay * (1 << (_reconnectAttempt - 1)); // exponential backoff
    final cappedDelay = delay > const Duration(seconds: 30) ? const Duration(seconds: 30) : delay;

    setState(() {
      _status = ConnectionStatus.reconnecting;
      _errorMessage = 'Reconectando... (tentativa $_reconnectAttempt/$_maxReconnectAttempts)';
    });

    _reconnectTimer?.cancel();
    _reconnectTimer = Timer(cappedDelay, () {
      if (mounted && !_userInitiatedDisconnect) {
        _connect();
      }
    });
  }

  Future<void> _disconnect() async {
    _userInitiatedDisconnect = true;
    _reconnectTimer?.cancel();
    _reconnectTimer = null;
    _reconnectAttempt = 0;

    await _audioSubscription?.cancel();
    _audioSubscription = null;

    if (await _recorder.isRecording()) {
      await _recorder.stop();
    }

    if (_socket != null && _serverAddress != null) {
      _socket!.send(Protocol.packBye(), _serverAddress!, _serverPort);
    }
    _socket?.close();
    _socket = null;
    _serverAddress = null;

    if (mounted) {
      setState(() {
        _status = ConnectionStatus.disconnected;
      });
    }
  }

  String _deviceName() => Platform.isIOS ? 'iPhone' : 'Android';

  @override
  Widget build(BuildContext context) {
    final isBusy = _status == ConnectionStatus.connecting ||
        _status == ConnectionStatus.reconnecting ||
        _status == ConnectionStatus.pairing;
    final isStreaming = _status == ConnectionStatus.streaming;

    return Scaffold(
      appBar: AppBar(
        title: const Text('OpenMic'),
        actions: [
          if (_deviceId != null)
            PopupMenuButton<String>(
              onSelected: (value) {
                if (value == 'unpair') {
                  _showUnpairDialog();
                }
              },
              itemBuilder: (context) => [
                const PopupMenuItem(
                  value: 'unpair',
                  child: Text('Desemparelhar dispositivo'),
                ),
              ],
            ),
        ],
      ),
      body: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const Text('Computadores encontrados na rede'),
            const SizedBox(height: 8),
            if (_foundDevices.isEmpty)
              const Padding(
                padding: EdgeInsets.symmetric(vertical: 8),
                child: Text(
                  'Procurando... verifique se o app do computador está aberto e com o servidor iniciado.',
                  style: TextStyle(color: Colors.grey),
                ),
              )
            else
              ..._foundDevices.values.map(
                (service) => Card(
                  margin: const EdgeInsets.only(bottom: 8),
                  child: ListTile(
                    leading: const Icon(Icons.computer),
                    title: Text(service.name),
                    subtitle: Text('${service.hostAddress}:${service.port}'),
                    onTap: (isStreaming || isBusy)
                        ? null
                        : () => _connectToDiscovered(service),
                  ),
                ),
              ),
            const SizedBox(height: 16),
            const Text('Ou digite o IP manualmente'),
            const SizedBox(height: 8),
            const Text('IP do computador (Linux)'),
            const SizedBox(height: 8),
            TextField(
              controller: _ipController,
              enabled: !isStreaming && !isBusy,
              keyboardType: TextInputType.number,
              decoration: const InputDecoration(
                border: OutlineInputBorder(),
                hintText: '192.168.0.10',
              ),
            ),
            const SizedBox(height: 16),
            const Text('Porta'),
            const SizedBox(height: 8),
            TextField(
              controller: _portController,
              enabled: !isStreaming && !isBusy,
              keyboardType: TextInputType.number,
              decoration: const InputDecoration(border: OutlineInputBorder()),
            ),
            const SizedBox(height: 24),
            FilledButton(
              onPressed: isBusy ? null : (isStreaming ? _disconnect : _connect),
              child: Text(
                isBusy
                    ? (_status == ConnectionStatus.pairing
                        ? 'Emparelhando...'
                        : 'Conectando...')
                    : (isStreaming ? 'Desconectar' : 'Conectar'),
              ),
            ),
            const SizedBox(height: 24),
            _StatusBadge(status: _status, errorMessage: _errorMessage),
          ],
        ),
      ),
    );
  }

  Future<void> _showUnpairDialog() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Desemparelhar'),
        content: const Text('Remover as credenciais deste dispositivo? Você precisará emparelhar novamente.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('Cancelar'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text('Desemparelhar'),
          ),
        ],
      ),
    );
    if (confirmed == true) {
      await _clearCredentials();
      setState(() {});
    }
  }
}

class _StatusBadge extends StatelessWidget {
  const _StatusBadge({required this.status, this.errorMessage});

  final ConnectionStatus status;
  final String? errorMessage;

  @override
  Widget build(BuildContext context) {
    final (label, color) = switch (status) {
      ConnectionStatus.disconnected => ('Desconectado', Colors.grey),
      ConnectionStatus.connecting => ('Conectando...', Colors.orange),
      ConnectionStatus.pairing => ('Aguardando emparelhamento...', Colors.blue),
      ConnectionStatus.reconnecting => ('Reconectando...', Colors.orange),
      ConnectionStatus.streaming => ('Transmitindo áudio', Colors.green),
      ConnectionStatus.error => (errorMessage ?? 'Erro', Colors.red),
    };
    return Row(
      children: [
        Icon(Icons.circle, size: 12, color: color),
        const SizedBox(width: 8),
        Expanded(child: Text(label)),
      ],
    );
  }
}
