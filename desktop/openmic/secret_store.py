"""Secure credential storage using OS keychain + Fernet encryption.

Schema:
  - A Fernet key is generated once per desktop install and stored in the
    OS keyring under "openmic/fernet_key".
  - Paired device credentials are encrypted with Fernet before writing to disk.
  - If the keyring is unavailable, falls back to plain JSON (same as before).

Dependencies: keyring, cryptography (stdlib-like, widely available).
"""

import base64
import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

_log = logging.getLogger(__name__)

_KEYRING_SERVICE = "openmic"
_KEYRING_USERNAME = "ferring"

# Fallback: derive a key from hostname + machine-id if keyring isn't available.
# This is NOT secure (any process can read the file), but it's the same threat
# model as the old plaintext JSON.


class SecretStore:
    """Encrypted credential backend wrapping a JSON file."""

    def __init__(self, path: Optional[Path] = None):
        if path is None:
            config_dir = Path.home() / ".config" / "openmic"
            config_dir.mkdir(parents=True, exist_ok=True)
            path = config_dir / "paired_devices.enc"
        self._path = path
        self._data: dict[str, dict] = {}
        self._fernet = self._init_fernet()
        self._load()

    def _init_fernet(self) -> Optional[Fernet]:
        """Get or create a Fernet encryption key from OS keyring."""
        import keyring

        try:
            key = keyring.get_password(_KEYRING_SERVICE, _KEYRING_USERNAME)
        except Exception:
            key = None

        if key is None:
            # First run: generate a new key and store it
            key = base64.urlsafe_b64encode(os.urandom(32)).decode()
            try:
                keyring.set_password(_KEYRING_SERVICE, _KEYRING_USERNAME, key)
            except Exception:
                _log.warning("keyring unavailable — credentials stored in plaintext")
                return None

        try:
            return Fernet(key.encode())
        except Exception:
            _log.warning("invalid keyring key — generating new one")
            key = base64.urlsafe_b64encode(os.urandom(32)).decode()
            try:
                keyring.set_password(_KEYRING_SERVICE, _KEYRING_USERNAME, key)
            except Exception:
                return None
            return Fernet(key.encode())

    def _load(self) -> None:
        data = {}
        if self._path.exists():
            try:
                with open(self._path, "rb") as f:
                    raw = f.read()
                if self._fernet is not None:
                    raw = self._fernet.decrypt(raw)
                data = json.loads(raw)
            except Exception:
                _log.debug("Failed to decrypt/load credentials — starting fresh")
                data = {}
        self._data = data

    def _save(self) -> None:
        try:
            raw = json.dumps(self._data).encode()
            if self._fernet is not None:
                raw = self._fernet.encrypt(raw)
            with open(self._path, "wb") as f:
                f.write(raw)
        except OSError:
            pass

    def add(self, device_id: bytes, auth_token: bytes, name: str) -> None:
        key = device_id.hex()
        self._data[key] = {
            "auth_token": auth_token.hex(),
            "name": name,
        }
        self._save()

    def get(self, device_id: bytes) -> Optional[bytes]:
        key = device_id.hex()
        entry = self._data.get(key)
        if entry:
            return bytes.fromhex(entry["auth_token"])
        return None

    def get_name(self, device_id: bytes) -> Optional[str]:
        key = device_id.hex()
        entry = self._data.get(key)
        if entry:
            return entry["name"]
        return None

    def remove(self, device_id: bytes) -> None:
        key = device_id.hex()
        if key in self._data:
            del self._data[key]
            self._save()

    def list_all(self) -> list[dict]:
        return [
            {"device_id": k, "name": v["name"]}
            for k, v in self._data.items()
        ]

    @property
    def is_encrypted(self) -> bool:
        return self._fernet is not None


def verify_pairing(device_id: bytes, auth_token: bytes, store: SecretStore) -> bool:
    """Verify if a paired HELLO has valid credentials."""
    stored = store.get(device_id)
    return stored is not None and stored == auth_token