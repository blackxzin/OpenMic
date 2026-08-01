"""Device pairing storage for the desktop app.

Stores trusted device IDs and auth tokens in a JSON file.
"""

import json
import os
from pathlib import Path
from typing import Dict, Optional

from . import protocol


class PairingStore:
    """Persists paired device credentials."""

    def __init__(self, path: Optional[Path] = None):
        if path is None:
            config_dir = Path.home() / ".config" / "openmic"
            config_dir.mkdir(parents=True, exist_ok=True)
            path = config_dir / "paired_devices.json"
        self._path = path
        self._data: Dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                with open(self._path, "r") as f:
                    self._data = json.load(f)
            except (json.JSONDecodeError, OSError):
                self._data = {}

    def _save(self) -> None:
        try:
            with open(self._path, "w") as f:
                json.dump(self._data, f)
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


def verify_pairing(device_id: bytes, auth_token: bytes, store: PairingStore) -> bool:
    """Verify if a paired HELLO has valid credentials."""
    stored = store.get(device_id)
    return stored is not None and stored == auth_token