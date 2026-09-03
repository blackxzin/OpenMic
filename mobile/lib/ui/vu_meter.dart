import 'package:flutter/material.dart';

import '../l10n/strings.dart';

/// Input-level bar shown while streaming.
class VuMeter extends StatelessWidget {
  const VuMeter({super.key, required this.level});

  final double level; // 0.0 to 1.0

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final ColorScheme colorScheme = theme.colorScheme;

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
      children: <Widget>[
        Row(
          children: <Widget>[
            Icon(Icons.graphic_eq, size: 18, color: colorScheme.primary),
            const SizedBox(width: 8),
            Text(Strings.tr('audio_level'), style: theme.textTheme.titleSmall),
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
            builder: (BuildContext context, BoxConstraints constraints) {
              final double barWidth =
                  (constraints.maxWidth * level).clamp(0.0, constraints.maxWidth);
              return Stack(
                children: <Widget>[
                  Container(
                    width: constraints.maxWidth,
                    height: 20,
                    decoration: BoxDecoration(
                      borderRadius: BorderRadius.circular(4),
                      color: colorScheme.surfaceContainerHighest,
                    ),
                  ),
                  AnimatedContainer(
                    duration: const Duration(milliseconds: 33),
                    width: barWidth,
                    height: 20,
                    decoration: BoxDecoration(
                      borderRadius: BorderRadius.circular(4),
                      color: barColor,
                    ),
                  ),
                  if (level > 0)
                    Positioned(
                      left: barWidth - 2,
                      top: 0,
                      bottom: 0,
                      child: Container(
                        width: 4,
                        color: Colors.white.withValues(alpha: 0.7),
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
