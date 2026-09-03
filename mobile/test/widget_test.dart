import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:openmic_mobile/l10n/strings.dart';
import 'package:openmic_mobile/main.dart';

void main() {
  setUp(() {
    // No plugins are registered in a widget test: shared_preferences gets a
    // mock, and mDNS/keystore failures are swallowed by the screen itself.
    SharedPreferences.setMockInitialValues(<String, Object>{});
    Strings.setLanguage('pt');
  });

  tearDown(() => Strings.setLanguage(Strings.defaultLanguage));

  testWidgets('Connection screen shows IP/port fields and connect button', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(const OpenMicApp());

    expect(find.text(Strings.tr('connect')), findsOneWidget);
    expect(find.text(Strings.tr('status_disconnected')), findsOneWidget);
    expect(find.byType(TextField), findsNWidgets(2));
  });

  testWidgets('Connect button reports an empty IP', (WidgetTester tester) async {
    await tester.pumpWidget(const OpenMicApp());

    await tester.tap(find.text(Strings.tr('connect')));
    await tester.pump();

    expect(find.text(Strings.tr('invalid_address')), findsOneWidget);
  });

  testWidgets('Quality selector offers the presets', (WidgetTester tester) async {
    await tester.pumpWidget(const OpenMicApp());

    expect(find.text(Strings.tr('quality_title')), findsOneWidget);
    expect(find.byType(DropdownButton<int>), findsOneWidget);
  });
}
