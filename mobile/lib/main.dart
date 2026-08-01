import 'dart:async';
import 'dart:io';
import 'dart:typed_data';

import 'package:bonsoir/bonsoir.dart';
import 'package:flutter/material.dart';
import 'package:record/record.dart';

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

enum ConnectionStatus { disconnected, connecting, streaming, reconnecting, error }

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

  BonsoirDiscovery? _discovery;
  StreamSubscription<BonsoirDiscoveryEvent>? _discoverySubscription;
  final Map<String, BonsoirService> _foundDevices = {};

  @override
  void initState() {
    super.initState();
    _startDiscovery();
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
    super.dispose();
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

      _socket!.send(
        Protocol.packHello(_deviceName()),
        _serverAddress!,
        _serverPort,
      );

      // Wait for pairing challenge response from desktop (HELLO v0)
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

      final challenge = await completer.future.timeout(
        const Duration(seconds: 2),
        onTimeout: () {
          if (!completer.isCompleted) completer.complete(null);
        },
      );

      await sub.cancel();

      if (challenge == null) {
        throw Exception('Servidor não respondeu — verifique o IP e porta');
      }

      final parsed = Protocol.unpack(challenge.data);
      if (parsed == null || parsed.$1 != Protocol.hello) {
        throw Exception('Resposta inesperada do servidor');
      }

      final audioStream = await _recorder.startStream(
        const RecordConfig(
          encoder: AudioEncoder.pcm16bits,
          sampleRate: Protocol.sampleRate,
          numChannels: Protocol.channels,
        ),
      );

      _sequence = 0;
      _audioSubscription = audioStream.listen(_onAudioChunk);

      // Reset reconnect state on successful connection
      _reconnectAttempt = 0;
      _reconnectTimer?.cancel();
      _reconnectTimer = null;

      setState(() {
        _status = ConnectionStatus.streaming;
      });
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
    final isBusy = _status == ConnectionStatus.connecting || _status == ConnectionStatus.reconnecting;
    final isStreaming = _status == ConnectionStatus.streaming;

    return Scaffold(
      appBar: AppBar(title: const Text('OpenMic')),
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
                    ? 'Conectando...'
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
