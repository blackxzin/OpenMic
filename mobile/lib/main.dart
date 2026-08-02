import 'dart:async';
import 'dart:ffi';
import 'dart:io';
import 'dart:typed_data';

import 'package:bonsoir/bonsoir.dart';
import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:opus_dart/opus_dart.dart';
import 'package:opus_flutter/opus_flutter.dart' as opus_flutter;
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
  bool _isPairingDialogVisible = false;

  // Opus encoder
  SimpleOpusEncoder? _opusEncoder;

  // VU meter state
  double _vuLevel = 0.0;  // 0.0 to 1.0
  Timer? _vuUpdateTimer;
  final List<int> _recentSamples = [];
  static const int _vuSampleWindow = 50;  // number of chunks to average

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
      if (event is BonsoirDiscoveryServiceFoundEvent) {
        final svc = event.service;
        if (svc != null) {
          svc.resolve(discovery.serviceResolver);
        }
      } else if (event is BonsoirDiscoveryServiceResolvedEvent) {
        final svc = event.service;
        if (svc != null) {
          setState(() => _foundDevices[svc.name] = svc);
        }
      } else if (event is BonsoirDiscoveryServiceLostEvent) {
        final svc = event.service;
        if (svc != null) {
          setState(() => _foundDevices.remove(svc.name));
        }
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
    _opusEncoder?.destroy();
    _vuUpdateTimer?.cancel();
    super.dispose();
  }

  Future<void> _initOpusEncoder() async {
    try {
      final DynamicLibrary lib = await opus_flutter.load();
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

  Future<void> _loadStoredCredentials() async {
    const storage = FlutterSecureStorage();
    final deviceIdHex = await storage.read(key: 'device_id');
    final authTokenHex = await storage.read(key: 'auth_token');
    if (deviceIdHex != null && authTokenHex != null) {
      _deviceId = Uint8List.fromList(deviceIdHex.split('').map((c) => int.parse(c, radix: 16)).toList());
      _authToken = Uint8List.fromList(authTokenHex.split('').map((c) => int.parse(c, radix: 16)).toList());
    }
  }

  Future<void> _saveCredentials(Uint8List deviceId, Uint8List authToken) async {
    const storage = FlutterSecureStorage();
    await storage.write(key: 'device_id', value: deviceId.map((b) => b.toRadixString(16).padLeft(2, '0')).join());
    await storage.write(key: 'auth_token', value: authToken.map((b) => b.toRadixString(16).padLeft(2, '0')).join());
    _deviceId = deviceId;
    _authToken = authToken;
  }

  Future<void> _clearCredentials() async {
    const storage = FlutterSecureStorage();
    await storage.delete(key: 'device_id');
    await storage.delete(key: 'auth_token');
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
    final encoder = _opusEncoder;
    if (socket == null || address == null || encoder == null) return;

    // Update VU meter
    _updateVuLevel(pcmChunk);

    try {
      // Encode PCM to Opus: opus_dart expects Int16List
      final pcmInt16 = Int16List.view(
        pcmChunk.buffer,
        pcmChunk.offsetInBytes,
        pcmChunk.lengthInBytes ~/ 2,
      );
      final opusData = encoder.encode(input: pcmInt16);
      if (opusData.isNotEmpty) {
        final opusBytes = Uint8List.fromList(opusData);
        socket.send(Protocol.packAudioOpus(_sequence, opusBytes), address, _serverPort);
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

    // Update VU meter
    _updateVuLevel(chunk);

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

  void _updateVuLevel(Uint8List pcmChunk) {
    // Calculate RMS (root mean square) of the audio chunk
    // pcmChunk is int16 little-endian
    if (pcmChunk.length < 2) return;

    double sumSquares = 0.0;
    final int sampleCount = pcmChunk.length ~/ 2;
    for (int i = 0; i < pcmChunk.length; i += 2) {
      // Convert two bytes to int16 (little-endian)
      final int sample = (pcmChunk[i] | (pcmChunk[i + 1] << 8));
      // Normalize to -1.0 to 1.0
      final double normalized = sample / 32768.0;
      sumSquares += normalized * normalized;
    }
    final double rms = sampleCount > 0 ? (sumSquares / sampleCount) : 0.0;
    final double level = rms.clamp(0.0, 1.0);

    // Smooth the level with exponential moving average
    _recentSamples.add((level * 1000).round());
    if (_recentSamples.length > _vuSampleWindow) {
      _recentSamples.removeAt(0);
    }
    final double avgLevel = _recentSamples.isNotEmpty
        ? _recentSamples.reduce((a, b) => a + b) / _recentSamples.length / 1000.0
        : 0.0;

    // Update UI at ~30fps
    if (_vuUpdateTimer?.isActive ?? false) return;
    _vuUpdateTimer = Timer(const Duration(milliseconds: 33), () {
      if (mounted) {
        setState(() {
          _vuLevel = avgLevel;
        });
      }
    });
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
            if (isStreaming) ...[
              const SizedBox(height: 24),
              _VuMeter(level: _vuLevel),
            ],
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
    String label;
    Color color;
    switch (status) {
      case ConnectionStatus.disconnected:
        label = 'Desconectado';
        color = Colors.grey;
        break;
      case ConnectionStatus.connecting:
        label = 'Conectando...';
        color = Colors.orange;
        break;
      case ConnectionStatus.pairing:
        label = 'Aguardando emparelhamento...';
        color = Colors.blue;
        break;
      case ConnectionStatus.reconnecting:
        label = 'Reconectando...';
        color = Colors.orange;
        break;
      case ConnectionStatus.streaming:
        label = 'Transmitindo áudio';
        color = Colors.green;
        break;
      case ConnectionStatus.error:
        label = errorMessage ?? 'Erro';
        color = Colors.red;
        break;
    }
    return Row(
      children: [
        Icon(Icons.circle, size: 12, color: color),
        const SizedBox(width: 8),
        Expanded(child: Text(label)),
      ],
    );
  }
}

class _VuMeter extends StatelessWidget {
  const _VuMeter({required this.level});

  final double level; // 0.0 to 1.0

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colorScheme = theme.colorScheme;

    // Determine color based on level
    Color barColor;
    if (level < 0.5) {
      barColor = colorScheme.primary;
    } else if (level < 0.8) {
      barColor = Colors.amber;
    } else {
      barColor = Colors.red;
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Icon(Icons.graphic_eq, size: 18, color: colorScheme.primary),
            const SizedBox(width: 8),
            Text(
              'Nível de áudio',
              style: theme.textTheme.titleSmall,
            ),
          ],
        ),
        const SizedBox(height: 8),
        Container(
          height: 20,
          decoration: BoxDecoration(
            border: Border.all(color: colorScheme.outline),
            borderRadius: BorderRadius.circular(4),
            color: colorScheme.surfaceContainerHighest,
          ),
          child: LayoutBuilder(
            builder: (context, constraints) {
              final barWidth = (constraints.maxWidth * level).clamp(0.0, constraints.maxWidth);
              return Stack(
                children: [
                  // Background track
                  Container(
                    width: constraints.maxWidth,
                    height: 20,
                    decoration: BoxDecoration(
                      borderRadius: BorderRadius.circular(4),
                      color: colorScheme.surfaceContainerHighest,
                    ),
                  ),
                  // Level bar
                  AnimatedContainer(
                    duration: const Duration(milliseconds: 33),
                    width: barWidth,
                    height: 20,
                    decoration: BoxDecoration(
                      borderRadius: BorderRadius.circular(4),
                      color: barColor,
                    ),
                  ),
                  // Peak marker
                  if (level > 0)
                    Positioned(
                      left: barWidth - 2,
                      top: 0,
                      bottom: 0,
                      child: Container(
                        width: 4,
                        color: Colors.white.withOpacity(0.7),
                      ),
                    ),
                ],
              );
            },
          ),
        ),
      ],
    );
  }
}
