"""Tests for PairingStore (SecretStore) and verify_pairing.

Uses a temp file path so the real ~/.config/openmic is never touched.
cryptography + keyring are available in this env (keyring may fall back to a
backend that has no secret service — __init__ tolerates that via try/except).
"""

import tempfile
import unittest
from pathlib import Path

from openmic.pairing import PairingStore, verify_pairing


class TestPairingStore(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "paired.json"
        self.store = PairingStore(path=self.path)

    def tearDown(self):
        self._tmp.cleanup()

    def _device(self, n=0):
        return bytes([n] * 16), bytes([n + 1] * 16)

    def test_add_and_get(self):
        dev_id, auth = self._device()
        self.store.add(dev_id, auth, "Pixel")
        self.assertEqual(self.store.get(dev_id), auth)
        self.assertEqual(self.store.get_name(dev_id), "Pixel")

    def test_get_missing_returns_none(self):
        self.assertIsNone(self.store.get(b"\x00" * 16))
        self.assertIsNone(self.store.get_name(b"\x00" * 16))

    def test_verify_pairing_true_false(self):
        dev_id, auth = self._device(n=5)
        self.store.add(dev_id, auth, "Pixel")
        self.assertTrue(verify_pairing(dev_id, auth, self.store))
        self.assertFalse(verify_pairing(dev_id, b"\x00" * 16, self.store))
        self.assertFalse(verify_pairing(b"\xFF" * 16, auth, self.store))

    def test_remove(self):
        dev_id, auth = self._device()
        self.store.add(dev_id, auth, "Pixel")
        self.store.remove(dev_id)
        self.assertIsNone(self.store.get(dev_id))
        self.assertEqual(self.store.list_all(), [])

    def test_remove_missing_is_noop(self):
        self.store.remove(b"\x00" * 16)  # must not raise
        self.assertEqual(self.store.list_all(), [])

    def test_persists_across_instances(self):
        dev_id, auth = self._device()
        self.store.add(dev_id, auth, "Pixel")
        # Reopen from the same path
        store2 = PairingStore(path=self.path)
        self.assertEqual(store2.get(dev_id), auth)
        self.assertEqual(store2.get_name(dev_id), "Pixel")
        self.assertTrue(verify_pairing(dev_id, auth, store2))

    def test_list_all_format(self):
        dev_id, auth = self._device()
        self.store.add(dev_id, auth, "iPhone")
        items = self.store.list_all()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["device_id"], dev_id.hex())
        self.assertEqual(items[0]["name"], "iPhone")

    def test_multiple_devices(self):
        for n in range(3):
            self.store.add(*self._device(n=n), name=f"dev{n}")
        self.assertEqual(len(self.store.list_all()), 3)
        for n in range(3):
            self.assertTrue(verify_pairing(*self._device(n=n), store=self.store))

    def test_overwrite_same_device_id(self):
        dev_id, auth = self._device()
        self.store.add(dev_id, auth, "Pixel")
        new_auth = bytes([9] * 16)
        self.store.add(dev_id, new_auth, "Pixel")
        self.assertEqual(self.store.get(dev_id), new_auth)
        self.assertEqual(len(self.store.list_all()), 1)


if __name__ == "__main__":
    unittest.main()
