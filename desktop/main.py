import asyncio
import logging
import re
import socket
import subprocess
import sys
import threading
from typing import Optional

from PySide6.QtCore import QObject, Signal, Qt
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSlider,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from openmic.discovery import ServiceAdvertiser
from openmic.server import AudioBridge, run_server
from openmic.virtual_mic import VirtualMic, VirtualMicError
from openmic.pairing import PairingStore

DEFAULT_PORT = 45820

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
_log = logging.getLogger(__name__)


_IP_ADDR_LINE = re.compile(r"^\d+:\s+(\S+)\s+inet\s+(\d+\.\d+\.\d+\.\d+)")


def get_local_ips() -> list[str]:
    """Local IPv4 addresses, WiFi interfaces first.

    Picking "whichever interface handles outbound internet traffic" doesn't
    work here: this machine's default route can go over a wired/USB interface
    while the phone is only reachable over WiFi. Interface *names* are a much
    more reliable signal than routing — Linux's predictable naming scheme
    prefixes wireless interfaces with "wl" (wlp1s0, wlan0, ...), unlike wired/
    USB-ethernet ("en...") or other interfaces.
    """
    by_iface: dict[str, str] = {}
    try:
        result = subprocess.run(
            ["ip", "-4", "-o", "addr", "show"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        for line in result.stdout.splitlines():
            match = _IP_ADDR_LINE.match(line)
            if match:
                iface, ip = match.groups()
                if not ip.startswith("127."):
                    by_iface[iface] = ip
    except (OSError, subprocess.SubprocessError):
        pass

    if not by_iface:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
                probe.connect(("8.8.8.8", 80))
                return [probe.getsockname()[0]]
        except OSError:
            return ["127.0.0.1"]

    wifi_ips = sorted(ip for iface, ip in by_iface.items() if iface.startswith("wl"))
    other_ips = sorted(ip for iface, ip in by_iface.items() if not iface.startswith("wl"))
    return wifi_ips + other_ips or ["127.0.0.1"]


class ServerSignals(QObject):
    log_message = Signal(str)
    device_connected = Signal(str, str)
    device_disconnected = Signal(str)
    pairing_request = Signal(str, str)  # IP, PIN


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

        def on_hello(addr, name, version, device_id, auth_token):
            _log.info("Device connected: %s (%s, v%d)", name, addr[0], version)
            self._signals.device_connected.emit(addr[0], name)

        def on_bye(addr):
            _log.info("Device disconnected: %s", addr[0])
            self._signals.device_disconnected.emit(addr[0])

        def on_pairing_request(addr, pin):
            _log.info("Pairing request from %s: PIN=%s", addr[0], pin)
            self._signals.pairing_request.emit(addr[0], pin)

        try:
            self._transport = self._loop.run_until_complete(
                run_server(self._host, self._port, self._bridge, on_hello, on_bye, on_pairing_request)
            )
            _log.info("Listening on %s:%d (UDP)", self._host, self._port)
            self._signals.log_message.emit(f"Ouvindo em {self._host}:{self._port} (UDP)")
            self._loop.run_forever()
        except OSError as exc:
            _log.error("Failed to start server: %s", exc)
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
        self.resize(420, 560)

        self._virtual_mic = VirtualMic()
        self._bridge = AudioBridge(sink_device_name="OpenMicSink")
        self._advertiser = ServiceAdvertiser()
        self._pairing_store = PairingStore()
        self._server_thread: Optional[ServerThread] = None
        self._local_ips = get_local_ips()

        self._signals = ServerSignals()
        self._signals.log_message.connect(self._append_log)
        self._signals.device_connected.connect(self._on_device_connected)
        self._signals.device_disconnected.connect(self._on_device_disconnected)
        self._signals.pairing_request.connect(self._on_pairing_request)

        layout = QVBoxLayout(self)

        ip_group = QGroupBox("Endereço deste computador")
        ip_layout = QVBoxLayout(ip_group)
        for index, ip in enumerate(self._local_ips):
            label = f"{ip} (usar este)" if index == 0 else ip
            ip_layout.addWidget(QLabel(label))
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

        # Volume/gain control
        gain_group = QGroupBox("Ganho do microfone")
        gain_layout = QVBoxLayout(gain_group)

        self._gain_slider = QSlider(Qt.Horizontal)
        self._gain_slider.setRange(0, 500)  # 0% to 500%
        self._gain_slider.setValue(100)      # 100% = 1.0x
        self._gain_slider.setTickPosition(QSlider.TicksBelow)
        self._gain_slider.setTickInterval(50)
        self._gain_slider.valueChanged.connect(self._on_gain_changed)
        gain_layout.addWidget(self._gain_slider)

        self._gain_label = QLabel("100%")
        self._gain_label.setAlignment(Qt.AlignCenter)
        gain_layout.addWidget(self._gain_label)

        layout.addWidget(gain_group)

        # Paired devices section
        self._devices_group = QGroupBox("Dispositivos emparelhados")
        devices_layout = QVBoxLayout(self._devices_group)
        self._devices_list = QListWidget()
        self._devices_list.setMaximumHeight(80)
        devices_layout.addWidget(self._devices_list)

        devices_buttons = QHBoxLayout()
        self._unpair_button = QPushButton("Remover selecionado")
        self._unpair_button.clicked.connect(self._unpair_selected)
        self._unpair_button.setEnabled(False)
        self._unpair_all_button = QPushButton("Remover todos")
        self._unpair_all_button.clicked.connect(self._unpair_all)
        self._unpair_all_button.setEnabled(False)
        devices_buttons.addWidget(self._unpair_button)
        devices_buttons.addWidget(self._unpair_all_button)
        devices_layout.addLayout(devices_buttons)
        layout.addWidget(self._devices_group)

        self._log = QTextEdit()
        self._log.setReadOnly(True)
        layout.addWidget(self._log)

        self._refresh_device_list()

        self._devices_list.itemSelectionChanged.connect(self._on_device_selection_changed)

    def _toggle_server(self) -> None:
        if self._server_thread is None:
            self._start_server()
        else:
            self._stop_server()

    def _start_server(self) -> None:
        try:
            self._virtual_mic.create()
            _log.info("Virtual microphone created")
        except VirtualMicError as exc:
            _log.error("Failed to create virtual mic: %s", exc)
            self._append_log(f"Falha ao criar microfone virtual: {exc}")
            return
        try:
            self._bridge.start_output()
            _log.info("Audio output started")
        except RuntimeError as exc:
            _log.error("Failed to open audio output: %s", exc)
            self._append_log(f"Falha ao abrir saída de áudio: {exc}")
            self._virtual_mic.destroy()
            return

        port = self._port_spin.value()
        self._server_thread = ServerThread("0.0.0.0", port, self._bridge, self._signals)
        self._server_thread.start()

        if self._local_ips:
            self._advertiser.start(port=port, ip=self._local_ips[0])
            _log.info("mDNS advertising started on %s:%d", self._local_ips[0], port)
            self._append_log("Anunciando na rede via mDNS (descoberta automática)")

        self._toggle_button.setText("Parar servidor")
        self._status_label.setText("Aguardando conexão do celular...")

    def _stop_server(self) -> None:
        if self._server_thread is not None:
            self._server_thread.stop()
            self._server_thread.join(timeout=2)
            self._server_thread = None
        self._advertiser.stop()
        self._bridge.stop_output()
        self._virtual_mic.destroy()
        _log.info("Server stopped")
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

    def _on_pairing_request(self, ip: str, pin: str) -> None:
        self._status_label.setText(f"Emparelhar: {pin}")
        self._append_log(f"Solicitação de emparelhamento de {ip} — PIN: {pin}")

    def _on_gain_changed(self, value: int) -> None:
        # value is 0-500, represents percentage
        gain = value / 100.0
        self._bridge.gain = gain
        self._gain_label.setText(f"{value}%")

    def _refresh_device_list(self) -> None:
        self._devices_list.clear()
        for device in self._pairing_store.list_all():
            item = QListWidgetItem(f"{device['name']} ({device['device_id'][:8]}...)")
            item.setData(Qt.UserRole, device["device_id"])
            self._devices_list.addItem(item)
        has_devices = self._devices_list.count() > 0
        self._unpair_all_button.setEnabled(has_devices)

    def _on_device_selection_changed(self) -> None:
        self._unpair_button.setEnabled(len(self._devices_list.selectedItems()) > 0)

    def _unpair_selected(self) -> None:
        for item in self._devices_list.selectedItems():
            device_id_hex = item.data(Qt.UserRole)
            device_id = bytes.fromhex(device_id_hex)
            name = item.text().split(" (")[0]
            self._pairing_store.remove(device_id)
            _log.info("Unpaired device: %s (%s...)", name, device_id_hex[:8])
            self._append_log(f"Dispositivo desemparelhado: {name}")
        self._refresh_device_list()

    def _unpair_all(self) -> None:
        reply = QMessageBox.question(
            self,
            "Confirmar",
            "Remover todos os dispositivos emparelhados?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        for device in self._pairing_store.list_all():
            device_id = bytes.fromhex(device["device_id"])
            self._pairing_store.remove(device_id)
        self._append_log("Todos os dispositivos foram desemparelhados")
        self._refresh_device_list()

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
