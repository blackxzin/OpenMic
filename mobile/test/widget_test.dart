import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:openmic_mobile/main.dart';

void main() {
  testWidgets('Connection screen shows IP/port fields and connect button', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(const OpenMicApp());

    expect(find.text('Conectar'), findsOneWidget);
    expect(find.text('Desconectado'), findsOneWidget);
    expect(find.byType(TextField), findsNWidgets(2));
  });

  testWidgets('Connect button is disabled with an empty IP', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(const OpenMicApp());

    await tester.tap(find.text('Conectar'));
    await tester.pump();

    expect(find.text('Informe um IP e porta válidos'), findsOneWidget);
  });
}
