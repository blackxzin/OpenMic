"""Device pairing storage for the Open Mic desktop app.

Always-alias to SecretStore — encrypted at rest by default when system keyring
is available, plaintext JSON fallback otherwise.

The public API is identical. Import PairingStore and verify_pairing from here.
"""

from .secret_store import SecretStore as PairingStore, verify_pairing