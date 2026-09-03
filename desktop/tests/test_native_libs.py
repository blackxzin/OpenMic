"""Tests for locating libraries that ctypes resolves by name.

Without the bundled fallback, an AppImage on a host that has no libopus
installed dies at import time — opuslib raises from find_library before any
of our code runs.
"""

import ctypes.util
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from openmic.native_libs import bundled_library_dir, find_bundled_library, library_fallback


class TestBundledLibraryDir(unittest.TestCase):
    def test_none_when_running_from_source(self):
        # sys.frozen is absent outside a PyInstaller build.
        self.assertIsNone(bundled_library_dir())

    def test_uses_meipass_when_frozen(self):
        with TemporaryDirectory() as tmp:
            with patch("openmic.native_libs.sys") as fake_sys:
                fake_sys.frozen = True
                fake_sys._MEIPASS = tmp
                self.assertEqual(bundled_library_dir(), Path(tmp))


class TestFindBundledLibrary(unittest.TestCase):
    def test_finds_a_versioned_soname(self):
        with TemporaryDirectory() as tmp:
            (Path(tmp) / "libopus.so.0").write_bytes(b"")
            found = find_bundled_library("opus", Path(tmp))
            self.assertTrue(found.endswith("libopus.so.0"))

    def test_missing_library_returns_none(self):
        with TemporaryDirectory() as tmp:
            self.assertIsNone(find_bundled_library("opus", Path(tmp)))

    def test_missing_directory_returns_none(self):
        self.assertIsNone(find_bundled_library("opus", Path("/nonexistent-openmic")))


class TestLibraryFallback(unittest.TestCase):
    def test_system_library_wins(self):
        with patch("ctypes.util.find_library", return_value="/usr/lib/libopus.so.0"):
            with library_fallback("opus"):
                self.assertEqual(ctypes.util.find_library("opus"), "/usr/lib/libopus.so.0")

    def test_bundled_library_fills_in(self):
        with TemporaryDirectory() as tmp:
            (Path(tmp) / "libopus.so.0").write_bytes(b"")
            with patch("ctypes.util.find_library", return_value=None), \
                 patch("openmic.native_libs.bundled_library_dir", return_value=Path(tmp)):
                with library_fallback("opus"):
                    self.assertTrue(ctypes.util.find_library("opus").endswith("libopus.so.0"))

    def test_other_names_are_untouched(self):
        with patch("ctypes.util.find_library", return_value=None):
            with library_fallback("opus"):
                self.assertIsNone(ctypes.util.find_library("somethingelse"))

    def test_original_lookup_is_restored(self):
        original = ctypes.util.find_library
        with library_fallback("opus"):
            pass
        self.assertIs(ctypes.util.find_library, original)
