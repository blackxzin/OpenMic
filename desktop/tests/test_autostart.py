"""Tests for the autostart .desktop entry helpers.

Regenerating Exec=/Icon=/Path= from sys.executable and __file__ at runtime
(rather than hardcoding an install path) is what makes the entry work
regardless of where the repo/venv actually live on a given machine.
"""

import unittest
from unittest.mock import patch

import main


class TestAutostartEntry(unittest.TestCase):
    def setUp(self):
        icons_dir = self._tmp_dir()
        self._patchers = [
            patch("main._AUTOSTART_DIR", self._tmp_dir()),
            patch("main._ICONS_DIR", icons_dir),
            patch("main._INSTALLED_ICON_PATH", icons_dir / "openmic.png"),
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
        self.assertFalse(main._is_autostart_enabled())

    def test_enabling_writes_a_valid_entry_referencing_this_install(self):
        main._set_autostart_enabled(True)

        self.assertTrue(main._is_autostart_enabled())
        contents = main._autostart_entry_path().read_text()
        self.assertIn("[Desktop Entry]", contents)
        self.assertIn("Name=OpenMic", contents)
        self.assertIn(f"Exec={main.sys.executable}", contents)
        self.assertIn(str(main._APP_DIR / "main.py"), contents)
        self.assertIn("X-GNOME-Autostart-enabled=true", contents)
        # Icon= must point at the copied, persistent path, not the source
        # icon — the latter can be a transient AppImage mount point.
        self.assertIn(f"Icon={main._INSTALLED_ICON_PATH}", contents)
        self.assertTrue(main._INSTALLED_ICON_PATH.exists())

    def test_disabling_removes_the_entry(self):
        main._set_autostart_enabled(True)
        self.assertTrue(main._is_autostart_enabled())

        main._set_autostart_enabled(False)
        self.assertFalse(main._is_autostart_enabled())

    def test_disabling_when_never_enabled_does_not_raise(self):
        main._set_autostart_enabled(False)  # no entry exists yet
        self.assertFalse(main._is_autostart_enabled())


if __name__ == "__main__":
    unittest.main()
