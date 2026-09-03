import 'dart:io';

/// UI strings in Portuguese and English.
///
/// Mirrors `desktop/openmic/i18n.py`: the two apps ship the same two
/// languages and pick one from the system locale, so a Brazilian user and an
/// English-speaking user both get a native-language UI out of the same build.
/// Flutter's own `intl`/ARB pipeline would add a codegen step for what is a
/// two-language, ~35-string surface.
class Strings {
  static const String defaultLanguage = 'en';
  static const List<String> supportedLanguages = <String>['en', 'pt'];

  static String _language = defaultLanguage;

  static String get language => _language;

  /// Force a language. Unsupported codes fall back to [defaultLanguage].
  static void setLanguage(String language) {
    _language = supportedLanguages.contains(language) ? language : defaultLanguage;
  }

  /// Map a locale string like `pt_BR.UTF-8` to a supported language code.
  static String? normalizeLanguage(String? locale) {
    if (locale == null || locale.isEmpty) return null;
    final code = locale.split('.').first.split('_').first.split('-').first.trim().toLowerCase();
    return supportedLanguages.contains(code) ? code : null;
  }

  /// Pick the language for [locale], defaulting when it isn't supported.
  static String detectLanguage(String? locale) {
    return normalizeLanguage(locale) ?? defaultLanguage;
  }

  /// Follow the device locale. Called once at startup.
  static void initFromPlatform() {
    String? locale;
    try {
      locale = Platform.localeName;
    } on Object {
      // Some platforms/test harnesses don't expose a locale; the default is
      // a fine answer and this must never block app startup.
      locale = null;
    }
    setLanguage(detectLanguage(locale));
  }

  /// Translate [key], replacing `{placeholder}` with [vars] entries.
  ///
  /// An unknown key returns the key itself: a missing string should look
  /// wrong on screen, not crash the app mid-call.
  static String tr(String key, [Map<String, Object?>? vars]) {
    final template = _strings[_language]?[key] ?? _strings[defaultLanguage]?[key];
    if (template == null) return key;
    if (vars == null || vars.isEmpty) return template;
    var out = template;
    vars.forEach((name, value) {
      out = out.replaceAll('{$name}', '$value');
    });
    return out;
  }

  static const Map<String, Map<String, String>> _strings = <String, Map<String, String>>{
    'en': <String, String>{
      'found_computers': 'Computers found on the network',
      'searching': 'Searching... make sure the desktop app is open with the server started.',
      'or_manual': 'Or type the IP manually',
      'computer_ip': 'Computer IP (Linux)',
      'port': 'Port',
      'connect': 'Connect',
      'disconnect': 'Disconnect',
      'connecting': 'Connecting...',
      'pairing_in_progress': 'Pairing...',
      'invalid_address': 'Enter a valid IP and port',
      'mic_permission_denied': 'Microphone permission denied',
      'server_no_reply': 'The server did not reply — check the IP and port',
      'invalid_response': 'Invalid response from the server',
      'unexpected_response': 'Unexpected response from the server: {type}',
      'pair_dialog_title': 'Pair device',
      'pair_dialog_body': 'Confirm the PIN on the computer:',
      'cancel': 'Cancel',
      'confirm': 'Confirm',
      'pair_failed': 'Could not confirm pairing',
      'reconnect_gave_up': 'Reached the maximum number of reconnect attempts',
      'reconnecting_attempt': 'Reconnecting... (attempt {attempt}/{max})',
      'unpair_menu': 'Unpair this device',
      'unpair_title': 'Unpair',
      'unpair_body': 'Remove this device\'s credentials? You will have to pair again.',
      'status_disconnected': 'Disconnected',
      'status_connecting': 'Connecting...',
      'status_pairing': 'Waiting for pairing...',
      'status_reconnecting': 'Reconnecting...',
      'status_streaming': 'Streaming audio',
      'status_error': 'Error',
      'audio_level': 'Audio level',
      'quality_title': 'Audio quality',
      'quality_low': 'Saver (16 kbps)',
      'quality_normal': 'Standard (24 kbps)',
      'quality_high': 'High (48 kbps)',
      'quality_hint': 'Lower uses less WiFi; higher sounds better on a good network.',
    },
    'pt': <String, String>{
      'found_computers': 'Computadores encontrados na rede',
      'searching': 'Procurando... verifique se o app do computador está aberto e com o servidor iniciado.',
      'or_manual': 'Ou digite o IP manualmente',
      'computer_ip': 'IP do computador (Linux)',
      'port': 'Porta',
      'connect': 'Conectar',
      'disconnect': 'Desconectar',
      'connecting': 'Conectando...',
      'pairing_in_progress': 'Emparelhando...',
      'invalid_address': 'Informe um IP e porta válidos',
      'mic_permission_denied': 'Permissão de microfone negada',
      'server_no_reply': 'Servidor não respondeu — verifique o IP e porta',
      'invalid_response': 'Resposta inválida do servidor',
      'unexpected_response': 'Resposta inesperada do servidor: {type}',
      'pair_dialog_title': 'Emparelhar dispositivo',
      'pair_dialog_body': 'Confirme o PIN no computador:',
      'cancel': 'Cancelar',
      'confirm': 'Confirmar',
      'pair_failed': 'Falha ao confirmar emparelhamento',
      'reconnect_gave_up': 'Máximo de tentativas de reconexão atingido',
      'reconnecting_attempt': 'Reconectando... (tentativa {attempt}/{max})',
      'unpair_menu': 'Desemparelhar dispositivo',
      'unpair_title': 'Desemparelhar',
      'unpair_body': 'Remover as credenciais deste dispositivo? Você precisará emparelhar novamente.',
      'status_disconnected': 'Desconectado',
      'status_connecting': 'Conectando...',
      'status_pairing': 'Aguardando emparelhamento...',
      'status_reconnecting': 'Reconectando...',
      'status_streaming': 'Transmitindo áudio',
      'status_error': 'Erro',
      'audio_level': 'Nível de áudio',
      'quality_title': 'Qualidade do áudio',
      'quality_low': 'Econômica (16 kbps)',
      'quality_normal': 'Padrão (24 kbps)',
      'quality_high': 'Alta (48 kbps)',
      'quality_hint': 'Menor consome menos WiFi; maior soa melhor em rede boa.',
    },
  };
}
