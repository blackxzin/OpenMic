import 'package:flutter/material.dart';

import '../l10n/strings.dart';
import '../models/connection_status.dart';

/// One-line connection state with a colour cue.
class StatusBadge extends StatelessWidget {
  const StatusBadge({super.key, required this.status, this.errorMessage});

  final ConnectionStatus status;
  final String? errorMessage;

  @override
  Widget build(BuildContext context) {
    String label;
    Color color;
    switch (status) {
      case ConnectionStatus.disconnected:
        label = Strings.tr('status_disconnected');
        color = Colors.grey;
        break;
      case ConnectionStatus.connecting:
        label = Strings.tr('status_connecting');
        color = Colors.orange;
        break;
      case ConnectionStatus.pairing:
        label = Strings.tr('status_pairing');
        color = Colors.blue;
        break;
      case ConnectionStatus.reconnecting:
        label = Strings.tr('status_reconnecting');
        color = Colors.orange;
        break;
      case ConnectionStatus.streaming:
        label = Strings.tr('status_streaming');
        color = Colors.green;
        break;
      case ConnectionStatus.error:
        label = errorMessage ?? Strings.tr('status_error');
        color = Colors.red;
        break;
    }
    return Row(
      children: <Widget>[
        Icon(Icons.circle, size: 12, color: color),
        const SizedBox(width: 8),
        Expanded(child: Text(label)),
      ],
    );
  }
}
