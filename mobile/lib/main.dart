import 'dart:async';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:record/record.dart';

import 'protocol.dart';

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

enum ConnectionStatus { disconnected, connecting, streaming, error }

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

  @override
  void dispose() {
    _disconnect();
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

      final audioStream = await _recorder.startStream(
        const RecordConfig(
          encoder: AudioEncoder.pcm16bits,
          sampleRate: Protocol.sampleRate,
          numChannels: Protocol.channels,
        ),
      );

      _sequence = 0;
      _audioSubscription = audioStream.listen(_onAudioChunk);

      setState(() {
        _status = ConnectionStatus.streaming;
      });
    } catch (error) {
      setState(() {
        _status = ConnectionStatus.error;
        _errorMessage = error.toString();
      });
      await _disconnect();
    }
  }

  void _onAudioChunk(Uint8List chunk) {
    final socket = _socket;
    final address = _serverAddress;
    if (socket == null || address == null) return;
    socket.send(Protocol.packAudio(_sequence, chunk), address, _serverPort);
    _sequence = (_sequence + 1) & 0xFFFFFFFF;
  }

  Future<void> _disconnect() async {
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
    final isBusy = _status == ConnectionStatus.connecting;
    final isStreaming = _status == ConnectionStatus.streaming;

    return Scaffold(
      appBar: AppBar(title: const Text('OpenMic')),
      body: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
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
