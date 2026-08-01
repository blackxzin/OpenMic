import asyncio
import socket
import sys
import threading
from typing import Optional

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QApplication,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from openmic.server import AudioBridge, run_server
from openmic.virtual_mic import VirtualMic, VirtualMicError

DEFAULT_PORT = 45820


def get_local_ips() -> list[str]:
    ips: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None):
            ip = info[4][0]
            if not ip.startswith("127.") and ":" not in ip:
                ips.add(ip)
    except socket.gaierror:
        pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("8.8.8.8", 80))
            ips.add(probe.getsockname()[0])
    except OSError:
        pass
    return sorted(ips) or ["127.0.0.1"]


class ServerSignals(QObject):
    log_message = Signal(str)
    device_connected = Signal(str, str)
    device_disconnected = Signal(str)


class ServerThread(threading.Thread):
    def __init__(self, host: str, port: int, bridge: AudioBridge, signals: ServerSignals):
        super().__init__(daemon=True)
        self._host = host
        self._port = port
        self._bridge = bridge
        self._signals = signals
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._transport = None

    def run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        def on_hello(addr, name):
            self._signals.device_connected.emit(addr[0], name)

        def on_bye(addr):
            self._signals.device_disconnected.emit(addr[0])

        try:
            self._transport = self._loop.run_until_complete(
                run_server(self._host, self._port, self._bridge, on_hello, on_bye)
            )
            self._signals.log_message.emit(f"Ouvindo em {self._host}:{self._port} (UDP)")
            self._loop.run_forever()
        except OSError as exc:
            self._signals.log_message.emit(f"Erro ao iniciar servidor: {exc}")
        finally:
            if self._transport is not None:
                self._transport.close()
            self._loop.close()

    def stop(self) -> None:
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("OpenMic")
        self.resize(420, 480)

        self._virtual_mic = VirtualMic()
        self._bridge = AudioBridge(sink_device_name="OpenMicSink")
        self._server_thread: Optional[ServerThread] = None

        self._signals = ServerSignals()
        self._signals.log_message.connect(self._append_log)
        self._signals.device_connected.connect(self._on_device_connected)
        self._signals.device_disconnected.connect(self._on_device_disconnected)

        layout = QVBoxLayout(self)

        ip_group = QGroupBox("Endereço deste computador")
        ip_layout = QVBoxLayout(ip_group)
        for ip in get_local_ips():
            ip_layout.addWidget(QLabel(ip))
        layout.addWidget(ip_group)

        port_row = QHBoxLayout()
        port_row.addWidget(QLabel("Porta:"))
        self._port_spin = QSpinBox()
        self._port_spin.setRange(1024, 65535)
        self._port_spin.setValue(DEFAULT_PORT)
        port_row.addWidget(self._port_spin)
        layout.addLayout(port_row)

        self._toggle_button = QPushButton("Iniciar servidor")
        self._toggle_button.clicked.connect(self._toggle_server)
        layout.addWidget(self._toggle_button)

        self._status_label = QLabel("Desligado")
        layout.addWidget(self._status_label)

        self._log = QTextEdit()
        self._log.setReadOnly(True)
        layout.addWidget(self._log)

    def _toggle_server(self) -> None:
        if self._server_thread is None:
            self._start_server()
        else:
            self._stop_server()

    def _start_server(self) -> None:
        try:
            self._virtual_mic.create()
        except VirtualMicError as exc:
            self._append_log(f"Falha ao criar microfone virtual: {exc}")
            return
        try:
            self._bridge.start_output()
        except RuntimeError as exc:
            self._append_log(f"Falha ao abrir saída de áudio: {exc}")
            self._virtual_mic.destroy()
            return

        port = self._port_spin.value()
        self._server_thread = ServerThread("0.0.0.0", port, self._bridge, self._signals)
        self._server_thread.start()

        self._toggle_button.setText("Parar servidor")
        self._status_label.setText("Aguardando conexão do celular...")

    def _stop_server(self) -> None:
        if self._server_thread is not None:
            self._server_thread.stop()
            self._server_thread.join(timeout=2)
            self._server_thread = None
        self._bridge.stop_output()
        self._virtual_mic.destroy()
        self._toggle_button.setText("Iniciar servidor")
        self._status_label.setText("Desligado")

    def _append_log(self, message: str) -> None:
        self._log.append(message)

    def _on_device_connected(self, ip: str, name: str) -> None:
        self._status_label.setText(f"Conectado: {name} ({ip})")
        self._append_log(f"Dispositivo conectado: {name} ({ip})")

    def _on_device_disconnected(self, ip: str) -> None:
        self._status_label.setText("Aguardando conexão do celular...")
        self._append_log(f"Dispositivo desconectado: {ip}")

    def closeEvent(self, event) -> None:
        self._stop_server()
        super().closeEvent(event)


def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
