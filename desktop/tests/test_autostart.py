"""Tests for the autostart .desktop entry helpers.

Regenerating Exec=/Icon=/Path= from sys.executable and __file__ at runtime
(rather than hardcoding an install path) is what makes the entry work
regardless of where the repo/venv actually live on a given machine.
"""

import sys
import unittest
from unittest.mock import patch

from openmic import desktop_entry


class TestAutostartEntry(unittest.TestCase):
    def setUp(self):
        icons_dir = self._tmp_dir()
        self._patchers = [
            patch("openmic.desktop_entry.AUTOSTART_DIR", self._tmp_dir()),
            patch("openmic.desktop_entry.ICONS_DIR", icons_dir),
            patch("openmic.desktop_entry.INSTALLED_ICON_PATH", icons_dir / "openmic.png"),
        ]
        for p in self._patchers:
            p.start()
            self.addCleanup(p.stop)

    @staticmethod
    def _tmp_dir():
        import tempfile
        from pathlib import Path

        return Path(tempfile.mkdtemp())

    def test_disabled_by_default_when_no_entry_exists(self):
        self.assertFalse(desktop_entry.is_autostart_enabled())

    def test_enabling_writes_a_valid_entry_referencing_this_install(self):
        desktop_entry.set_autostart_enabled(True)

        self.assertTrue(desktop_entry.is_autostart_enabled())
        contents = desktop_entry.autostart_entry_path().read_text()
        self.assertIn("[Desktop Entry]", contents)
        self.assertIn("Name=OpenMic", contents)
        self.assertIn(f"Exec={sys.executable}", contents)
        self.assertIn(str(desktop_entry.APP_DIR / "main.py"), contents)
        self.assertIn("X-GNOME-Autostart-enabled=true", contents)
        # Icon= must point at the copied, persistent path, not the source
        # icon — the latter can be a transient AppImage mount point.
        self.assertIn(f"Icon={desktop_entry.INSTALLED_ICON_PATH}", contents)
        self.assertTrue(desktop_entry.INSTALLED_ICON_PATH.exists())

    def test_disabling_removes_the_entry(self):
        desktop_entry.set_autostart_enabled(True)
        self.assertTrue(desktop_entry.is_autostart_enabled())

        desktop_entry.set_autostart_enabled(False)
        self.assertFalse(desktop_entry.is_autostart_enabled())

    def test_disabling_when_never_enabled_does_not_raise(self):
        desktop_entry.set_autostart_enabled(False)  # no entry exists yet
        self.assertFalse(desktop_entry.is_autostart_enabled())


if __name__ == "__main__":
    unittest.main()
