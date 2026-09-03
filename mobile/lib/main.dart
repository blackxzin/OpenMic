import 'package:flutter/material.dart';

import 'l10n/strings.dart';
import 'ui/connection_screen.dart';

void main() {
  Strings.initFromPlatform();
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
