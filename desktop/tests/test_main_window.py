"""Smoke test: the window builds and its quality panel renders both states.

The UI is assembled from several _build_* helpers that wire widgets to
methods by name; without this, a renamed attribute or a bad translation
placeholder only shows up when a human opens the app.
"""

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

import main
from openmic.stream_stats import StreamSnapshot


class TestMainWindow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        # A tray icon would keep the app alive past the test run, and
        # PairingStore would touch the real ~/.config/openmic file.
        patchers = [
            patch("main.QSystemTrayIcon.isSystemTrayAvailable", return_value=False),
            patch("main.PairingStore"),
            patch("main.get_local_ips", return_value=["192.168.0.10", "10.0.0.2"]),
        ]
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.window = main.MainWindow()
        self.addCleanup(self.window.deleteLater)

    def test_starts_idle(self):
        self.assertEqual(self.window._toggle_button.text(), main.tr("start_server"))
        self.assertEqual(self.window._quality_label.text(), main.tr("quality_idle"))
        self.assertFalse(self.window._stats_timer.isActive())

    def test_quality_panel_shows_live_numbers(self):
        snapshot = StreamSnapshot(
            packets=500,
            lost=5,
            loss_percent=1.0,
            jitter_ms=12.0,
            bitrate_kbps=24.0,
            buffer_ms=60.0,
            receiving=True,
        )
        with patch.object(self.window._bridge, "stats", return_value=snapshot):
            self.window._refresh_stats()
        self.assertIn("24", self.window._quality_label.text())
        self.assertIn("500", self.window._quality_detail_label.text())

    def test_quality_panel_returns_to_idle_when_audio_stops(self):
        with patch.object(self.window._bridge, "stats", return_value=StreamSnapshot()):
            self.window._refresh_stats()
        self.assertEqual(self.window._quality_label.text(), main.tr("quality_idle"))
        self.assertEqual(self.window._quality_detail_label.text(), "")

    def test_gain_slider_drives_the_bridge(self):
        self.window._gain_slider.setValue(250)
        self.assertAlmostEqual(self.window._bridge.gain, 2.5)
        self.assertEqual(self.window._gain_label.text(), "250%")

    def test_pairing_request_surfaces_the_pin(self):
        self.window._on_pairing_request("10.0.0.5", "123456")
        self.assertIn("123456", self.window._status_label.text())


if __name__ == "__main__":
    unittest.main()
