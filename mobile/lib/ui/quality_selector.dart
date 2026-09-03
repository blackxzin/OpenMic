import 'package:flutter/material.dart';

import '../l10n/strings.dart';
import '../protocol.dart';

/// Picks the Opus bitrate used for streaming.
///
/// Lower settings survive a congested network; higher ones sound noticeably
/// better when the WiFi can carry them. Locked while streaming because the
/// encoder is created once per session.
class QualitySelector extends StatelessWidget {
  const QualitySelector({
    super.key,
    required this.bitrate,
    required this.enabled,
    required this.onChanged,
  });

  final int bitrate;
  final bool enabled;
  final ValueChanged<int> onChanged;

  static const Map<int, String> _labelKeys = <int, String>{
    16000: 'quality_low',
    24000: 'quality_normal',
    48000: 'quality_high',
  };

  static String labelFor(int value) => Strings.tr(_labelKeys[value] ?? 'quality_normal');

  /// Nearest offered preset. A stored value from another build (or a hand
  /// edited preference) must still match one of the dropdown's items, or
  /// Flutter asserts on a value that isn't in the list.
  static int snapToPreset(int value) {
    int best = Protocol.opusBitratePresets.first;
    for (final int preset in Protocol.opusBitratePresets) {
      if ((preset - value).abs() < (best - value).abs()) best = preset;
    }
    return best;
  }

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        Text(Strings.tr('quality_title'), style: theme.textTheme.titleSmall),
        const SizedBox(height: 8),
        DropdownButton<int>(
          value: bitrate,
          isExpanded: true,
          items: Protocol.opusBitratePresets
              .map((int value) => DropdownMenuItem<int>(
                    value: value,
                    child: Text(labelFor(value)),
                  ))
              .toList(),
          onChanged: enabled
              ? (int? value) {
                  if (value != null) onChanged(value);
                }
              : null,
        ),
        const SizedBox(height: 4),
        Text(
          Strings.tr('quality_hint'),
          style: theme.textTheme.bodySmall?.copyWith(color: Colors.grey),
        ),
      ],
    );
  }
}
