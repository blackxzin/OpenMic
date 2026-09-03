import 'package:bonsoir/bonsoir.dart';
import 'package:flutter/material.dart';

import '../l10n/strings.dart';
import '../models/connection_status.dart';
import 'quality_selector.dart';
import 'status_badge.dart';
import 'vu_meter.dart';

/// The connection screen's layout, with no networking or audio state of its
/// own — everything it shows arrives as parameters and every interaction
/// leaves through a callback.
class ConnectionBody extends StatelessWidget {
  const ConnectionBody({
    super.key,
    required this.foundDevices,
    required this.ipController,
    required this.portController,
    required this.status,
    required this.errorMessage,
    required this.bitrate,
    required this.vuLevel,
    required this.onConnectDiscovered,
    required this.onPrimaryAction,
    required this.onBitrateChanged,
  });

  final Iterable<BonsoirService> foundDevices;
  final TextEditingController ipController;
  final TextEditingController portController;
  final ConnectionStatus status;
  final String? errorMessage;
  final int bitrate;
  final double vuLevel;
  final ValueChanged<BonsoirService> onConnectDiscovered;
  final VoidCallback onPrimaryAction;
  final ValueChanged<int> onBitrateChanged;

  bool get _isBusy =>
      status == ConnectionStatus.connecting ||
      status == ConnectionStatus.reconnecting ||
      status == ConnectionStatus.pairing;

  bool get _isStreaming => status == ConnectionStatus.streaming;

  String get _primaryLabel {
    if (_isBusy) {
      return status == ConnectionStatus.pairing
          ? Strings.tr('pairing_in_progress')
          : Strings.tr('connecting');
    }
    return _isStreaming ? Strings.tr('disconnect') : Strings.tr('connect');
  }

  @override
  Widget build(BuildContext context) {
    final bool inputsEnabled = !_isStreaming && !_isBusy;
    return SingleChildScrollView(
      padding: const EdgeInsets.all(24),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          Text(Strings.tr('found_computers')),
          const SizedBox(height: 8),
          if (foundDevices.isEmpty)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 8),
              child: Text(
                Strings.tr('searching'),
                style: const TextStyle(color: Colors.grey),
              ),
            )
          else
            ...foundDevices.map(
              (BonsoirService service) => Card(
                margin: const EdgeInsets.only(bottom: 8),
                child: ListTile(
                  leading: const Icon(Icons.computer),
                  title: Text(service.name),
                  subtitle: Text('${service.hostAddress}:${service.port}'),
                  onTap: inputsEnabled ? () => onConnectDiscovered(service) : null,
                ),
              ),
            ),
          const SizedBox(height: 16),
          Text(Strings.tr('or_manual')),
          const SizedBox(height: 8),
          Text(Strings.tr('computer_ip')),
          const SizedBox(height: 8),
          TextField(
            controller: ipController,
            enabled: inputsEnabled,
            keyboardType: TextInputType.number,
            decoration: const InputDecoration(
              border: OutlineInputBorder(),
              hintText: '192.168.0.10',
            ),
          ),
          const SizedBox(height: 16),
          Text(Strings.tr('port')),
          const SizedBox(height: 8),
          TextField(
            controller: portController,
            enabled: inputsEnabled,
            keyboardType: TextInputType.number,
            decoration: const InputDecoration(border: OutlineInputBorder()),
          ),
          const SizedBox(height: 16),
          QualitySelector(
            bitrate: bitrate,
            enabled: inputsEnabled,
            onChanged: onBitrateChanged,
          ),
          const SizedBox(height: 24),
          FilledButton(
            onPressed: _isBusy ? null : onPrimaryAction,
            child: Text(_primaryLabel),
          ),
          if (_isStreaming) ...<Widget>[
            const SizedBox(height: 24),
            VuMeter(level: vuLevel),
          ],
          const SizedBox(height: 24),
          StatusBadge(status: status, errorMessage: errorMessage),
        ],
      ),
    );
  }
}
