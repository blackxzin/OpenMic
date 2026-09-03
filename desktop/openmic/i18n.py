"""Interface strings in Portuguese and English.

The apps are used on both sides of a bilingual README, so the UI follows the
system locale instead of being hardcoded to one language. Gettext/.mo files
would need a compile step in the AppImage build for a two-language, ~50-string
surface — a plain dict keeps the build a single PyInstaller call.

Set ``OPENMIC_LANG=pt`` or ``OPENMIC_LANG=en`` to override the detection.
"""

import os
from typing import Optional

DEFAULT_LANGUAGE = "en"
SUPPORTED_LANGUAGES = ("en", "pt")

_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "group_address": "This computer's address",
        "use_this_address": "{ip} (use this one)",
        "port": "Port:",
        "start_server": "Start server",
        "stop_server": "Stop server",
        "status_off": "Off",
        "status_waiting": "Waiting for the phone to connect...",
        "status_connected": "Connected: {name} ({ip})",
        "status_pairing": "Pair using PIN: {pin}",
        "group_gain": "Microphone gain",
        "noise_suppression": "Background noise reduction",
        "autostart": "Start with the system",
        "group_devices": "Paired devices",
        "remove_selected": "Remove selected",
        "remove_all": "Remove all",
        "confirm_title": "Confirm",
        "confirm_unpair_all": "Remove every paired device?",
        "group_quality": "Connection quality",
        "quality_idle": "No audio arriving",
        "quality_line": "{bitrate:.0f} kbps · loss {loss:.1f}% · jitter {jitter:.0f} ms",
        "quality_detail": "Buffer {buffer:.0f} ms · {packets} packets · {lost} lost",
        "log_listening": "Listening on {host}:{port} (UDP)",
        "log_mdns": "Advertising on the network via mDNS (automatic discovery)",
        "log_device_connected": "Device connected: {name} ({ip})",
        "log_device_disconnected": "Device disconnected: {ip}",
        "log_pairing_request": "Pairing request from {ip} — PIN: {pin}",
        "log_unpaired": "Device unpaired: {name}",
        "log_unpaired_all": "Every device was unpaired",
        "error_server": "Failed to start the server: {error}",
        "error_virtual_mic": "Failed to create the virtual microphone: {error}",
        "error_audio_output": "Failed to open the audio output: {error}",
        "error_autostart": "Failed to configure autostart: {error}",
        "tray_show": "Show",
        "tray_quit": "Quit",
        "tray_minimized": "Still running in the tray. Click the icon to open it again.",
    },
    "pt": {
        "group_address": "Endereço deste computador",
        "use_this_address": "{ip} (usar este)",
        "port": "Porta:",
        "start_server": "Iniciar servidor",
        "stop_server": "Parar servidor",
        "status_off": "Desligado",
        "status_waiting": "Aguardando conexão do celular...",
        "status_connected": "Conectado: {name} ({ip})",
        "status_pairing": "Emparelhar com o PIN: {pin}",
        "group_gain": "Ganho do microfone",
        "noise_suppression": "Redução de ruído de fundo",
        "autostart": "Iniciar com o sistema",
        "group_devices": "Dispositivos emparelhados",
        "remove_selected": "Remover selecionado",
        "remove_all": "Remover todos",
        "confirm_title": "Confirmar",
        "confirm_unpair_all": "Remover todos os dispositivos emparelhados?",
        "group_quality": "Qualidade da conexão",
        "quality_idle": "Nenhum áudio chegando",
        "quality_line": "{bitrate:.0f} kbps · perda {loss:.1f}% · jitter {jitter:.0f} ms",
        "quality_detail": "Buffer {buffer:.0f} ms · {packets} pacotes · {lost} perdidos",
        "log_listening": "Ouvindo em {host}:{port} (UDP)",
        "log_mdns": "Anunciando na rede via mDNS (descoberta automática)",
        "log_device_connected": "Dispositivo conectado: {name} ({ip})",
        "log_device_disconnected": "Dispositivo desconectado: {ip}",
        "log_pairing_request": "Solicitação de emparelhamento de {ip} — PIN: {pin}",
        "log_unpaired": "Dispositivo desemparelhado: {name}",
        "log_unpaired_all": "Todos os dispositivos foram desemparelhados",
        "error_server": "Erro ao iniciar servidor: {error}",
        "error_virtual_mic": "Falha ao criar microfone virtual: {error}",
        "error_audio_output": "Falha ao abrir saída de áudio: {error}",
        "error_autostart": "Falha ao configurar início automático: {error}",
        "tray_show": "Mostrar",
        "tray_quit": "Sair",
        "tray_minimized": "Continua rodando na bandeja. Clique no ícone para abrir de novo.",
    },
}

_LOCALE_ENV_VARS = ("OPENMIC_LANG", "LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE")

_language = DEFAULT_LANGUAGE


def normalize_language(value: Optional[str]) -> Optional[str]:
    """Map a locale string like ``pt_BR.UTF-8`` to a supported language code."""
    if not value:
        return None
    code = value.split(".")[0].split("_")[0].split("-")[0].strip().lower()
    return code if code in SUPPORTED_LANGUAGES else None


def detect_language(environ: Optional[dict] = None) -> str:
    """First supported language named by the environment, else the default."""
    env = os.environ if environ is None else environ
    for name in _LOCALE_ENV_VARS:
        language = normalize_language(env.get(name))
        if language:
            return language
    return DEFAULT_LANGUAGE


def set_language(language: str) -> None:
    """Force a language. Unsupported codes fall back to the default."""
    global _language
    _language = language if language in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE


def get_language() -> str:
    return _language


def tr(key: str, **kwargs) -> str:
    """Translate ``key``, interpolating ``kwargs``.

    An unknown key returns the key itself rather than raising: a missing
    string should look wrong in the UI, not crash the app mid-session.
    """
    template = _STRINGS[_language].get(key) or _STRINGS[DEFAULT_LANGUAGE].get(key)
    if template is None:
        return key
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError):
        return template


set_language(detect_language())
