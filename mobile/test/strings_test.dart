import 'package:flutter_test/flutter_test.dart';

import 'package:openmic_mobile/l10n/strings.dart';

void main() {
  group('Strings', () {
    tearDown(() => Strings.setLanguage(Strings.defaultLanguage));

    test('locale variants map to a supported language', () {
      expect(Strings.detectLanguage('pt_BR.UTF-8'), 'pt');
      expect(Strings.detectLanguage('en-GB'), 'en');
    });

    test('unsupported or missing locales fall back to the default', () {
      expect(Strings.detectLanguage('ja_JP'), Strings.defaultLanguage);
      expect(Strings.detectLanguage(null), Strings.defaultLanguage);
      expect(Strings.detectLanguage(''), Strings.defaultLanguage);
    });

    test('setLanguage rejects unsupported codes', () {
      Strings.setLanguage('ja');
      expect(Strings.language, Strings.defaultLanguage);
    });

    test('translates per language', () {
      Strings.setLanguage('pt');
      expect(Strings.tr('connect'), 'Conectar');
      Strings.setLanguage('en');
      expect(Strings.tr('connect'), 'Connect');
    });

    test('interpolates placeholders', () {
      Strings.setLanguage('en');
      final String text = Strings.tr('reconnecting_attempt', <String, Object?>{
        'attempt': 2,
        'max': 5,
      });
      expect(text, contains('2/5'));
    });

    test('unknown key returns the key itself', () {
      expect(Strings.tr('no_such_key'), 'no_such_key');
    });
  });
}
