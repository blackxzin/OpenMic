"""Regression test: stopping and immediately restarting the UDP server on
the same port must not fail with "Address already in use".

transport.close() only schedules the underlying socket's real close via
call_soon(); if the event loop is closed before that callback runs, the fd
leaks until garbage collection, and a fast restart intermittently loses the
race against the old (still-open) socket.
"""

import os
import sys
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication

import main
from openmic.server import AudioBridge

_TEST_PORT = 45831


class TestServerThreadRestart(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_stop_then_restart_on_same_port_does_not_raise(self):
        bridge = AudioBridge("OpenMicSink")
        signals = main.ServerSignals()
        errors: list[str] = []
        signals.log_message.connect(
            lambda msg: errors.append(msg) if "Erro" in msg or "Endereço" in msg else None
        )

        for _ in range(3):
            thread = main.ServerThread("127.0.0.1", _TEST_PORT, bridge, signals)
            thread.start()
            time.sleep(0.2)
            thread.stop()
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())

        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
