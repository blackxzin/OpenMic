"""OpenMic desktop app: virtual microphone fed by the phone over WiFi."""

import asyncio
import logging
import sys
import threading
from typing import Optional

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QSlider,
    QSpinBox,
    QSystemTrayIcon,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from openmic import desktop_entry
from openmic.discovery import ServiceAdvertiser
from openmic.i18n import tr
from openmic.net_ifaces import get_local_ips
from openmic.pairing import PairingStore
from openmic.server import AudioBridge, run_server
from openmic.virtual_mic import VirtualMic, VirtualMicError

DEFAULT_PORT = 45820
STATS_REFRESH_MS = 1000

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
_log = logging.getLogger(__name__)


class ServerSignals(QObject):
    log_message = Signal(str)
    # Errors travel on their own signal instead of being pattern-matched out
    # of the log text — the log is translated, so matching on wording would
    # break in whichever language the string isn't written in.
    error_message = Signal(str)
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
            self._signals.log_message.emit(tr("log_listening", host=self._host, port=self._port))
            self._loop.run_forever()
        except OSError as exc:
            _log.error("Failed to start server: %s", exc)
            self._signals.error_message.emit(tr("error_server", error=exc))
        finally:
            if self._transport is not None:
                self._transport.close()
                # transport.close() only *schedules* the underlying socket's
                # real close via call_soon; run_forever() already returned
                # (we're here because of loop.stop()), so without this the
                # scheduled callback never runs and loop.close() below never
                # releases the fd — the next start then fails to rebind with
                # "Address already in use".
                self._loop.run_until_complete(asyncio.sleep(0))
            self._loop.close()

    def stop(self) -> None:
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("OpenMic")
        self.resize(420, 640)

        self._virtual_mic = VirtualMic()
        self._bridge = AudioBridge(sink_device_name="OpenMicSink")
        self._advertiser = ServiceAdvertiser()
        self._pairing_store = PairingStore()
        self._server_thread: Optional[ServerThread] = None
        self._local_ips = get_local_ips()

        self._signals = ServerSignals()
        self._signals.log_message.connect(self._append_log)
        self._signals.error_message.connect(self._append_log)
        self._signals.device_connected.connect(self._on_device_connected)
        self._signals.device_disconnected.connect(self._on_device_disconnected)
        self._signals.pairing_request.connect(self._on_pairing_request)

        layout = QVBoxLayout(self)
        layout.addWidget(self._build_address_group())
        layout.addLayout(self._build_port_row())

        self._toggle_button = QPushButton(tr("start_server"))
        self._toggle_button.clicked.connect(self._toggle_server)
        layout.addWidget(self._toggle_button)

        self._status_label = QLabel(tr("status_off"))
        layout.addWidget(self._status_label)

        layout.addWidget(self._build_quality_group())
        layout.addWidget(self._build_gain_group())

        self._noise_suppression_checkbox = QCheckBox(tr("noise_suppression"))
        self._noise_suppression_checkbox.setChecked(True)
        self._noise_suppression_checkbox.toggled.connect(self._on_noise_suppression_toggled)
        layout.addWidget(self._noise_suppression_checkbox)

        self._autostart_checkbox = QCheckBox(tr("autostart"))
        self._autostart_checkbox.setChecked(desktop_entry.is_autostart_enabled())
        self._autostart_checkbox.toggled.connect(self._on_autostart_toggled)
        layout.addWidget(self._autostart_checkbox)

        layout.addWidget(self._build_devices_group())

        self._log = QTextEdit()
        self._log.setReadOnly(True)
        layout.addWidget(self._log)

        self._refresh_device_list()

        self._stats_timer = QTimer(self)
        self._stats_timer.setInterval(STATS_REFRESH_MS)
        self._stats_timer.timeout.connect(self._refresh_stats)

        self._tray: Optional[QSystemTrayIcon] = None
        self._setup_tray_icon()

    # ---------------------------------------------------------------- layout

    def _build_address_group(self) -> QGroupBox:
        group = QGroupBox(tr("group_address"))
        group_layout = QVBoxLayout(group)
        for index, ip in enumerate(self._local_ips):
            label = tr("use_this_address", ip=ip) if index == 0 else ip
            group_layout.addWidget(QLabel(label))
        return group

    def _build_port_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(QLabel(tr("port")))
        self._port_spin = QSpinBox()
        self._port_spin.setRange(1024, 65535)
        self._port_spin.setValue(DEFAULT_PORT)
        row.addWidget(self._port_spin)
        return row

    def _build_quality_group(self) -> QGroupBox:
        group = QGroupBox(tr("group_quality"))
        group_layout = QVBoxLayout(group)
        self._quality_label = QLabel(tr("quality_idle"))
        self._quality_detail_label = QLabel("")
        self._quality_detail_label.setEnabled(False)  # secondary, dimmed
        group_layout.addWidget(self._quality_label)
        group_layout.addWidget(self._quality_detail_label)
        return group

    def _build_gain_group(self) -> QGroupBox:
        group = QGroupBox(tr("group_gain"))
        group_layout = QVBoxLayout(group)

        self._gain_slider = QSlider(Qt.Horizontal)
        self._gain_slider.setRange(0, 500)  # 0% to 500%
        self._gain_slider.setValue(100)      # 100% = 1.0x
        self._gain_slider.setTickPosition(QSlider.TicksBelow)
        self._gain_slider.setTickInterval(50)
        self._gain_slider.valueChanged.connect(self._on_gain_changed)
        group_layout.addWidget(self._gain_slider)

        self._gain_label = QLabel("100%")
        self._gain_label.setAlignment(Qt.AlignCenter)
        group_layout.addWidget(self._gain_label)
        return group

    def _build_devices_group(self) -> QGroupBox:
        group = QGroupBox(tr("group_devices"))
        group_layout = QVBoxLayout(group)
        self._devices_list = QListWidget()
        self._devices_list.setMaximumHeight(80)
        self._devices_list.itemSelectionChanged.connect(self._on_device_selection_changed)
        group_layout.addWidget(self._devices_list)

        buttons = QHBoxLayout()
        self._unpair_button = QPushButton(tr("remove_selected"))
        self._unpair_button.clicked.connect(self._unpair_selected)
        self._unpair_button.setEnabled(False)
        self._unpair_all_button = QPushButton(tr("remove_all"))
        self._unpair_all_button.clicked.connect(self._unpair_all)
        self._unpair_all_button.setEnabled(False)
        buttons.addWidget(self._unpair_button)
        buttons.addWidget(self._unpair_all_button)
        group_layout.addLayout(buttons)
        return group

    # --------------------------------------------------------------- server

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
            self._append_log(tr("error_virtual_mic", error=exc))
            return
        try:
            self._bridge.start_output()
            _log.info("Audio output started")
        except RuntimeError as exc:
            _log.error("Failed to open audio output: %s", exc)
            self._append_log(tr("error_audio_output", error=exc))
            self._virtual_mic.destroy()
            return

        port = self._port_spin.value()
        self._server_thread = ServerThread("0.0.0.0", port, self._bridge, self._signals)
        self._server_thread.start()

        if self._local_ips:
            self._advertiser.start(port=port, ip=self._local_ips[0])
            _log.info("mDNS advertising started on %s:%d", self._local_ips[0], port)
            self._append_log(tr("log_mdns"))

        self._stats_timer.start()
        self._toggle_button.setText(tr("stop_server"))
        self._status_label.setText(tr("status_waiting"))

    def _stop_server(self) -> None:
        if self._server_thread is not None:
            self._server_thread.stop()
            self._server_thread.join(timeout=2)
            self._server_thread = None
        self._advertiser.stop()
        self._bridge.stop_output()
        self._virtual_mic.destroy()
        self._stats_timer.stop()
        self._reset_quality_labels()
        _log.info("Server stopped")
        self._toggle_button.setText(tr("start_server"))
        self._status_label.setText(tr("status_off"))

    # ---------------------------------------------------------------- stats

    def _refresh_stats(self) -> None:
        stats = self._bridge.stats()
        if not stats.receiving:
            self._reset_quality_labels()
            return
        self._quality_label.setText(
            tr(
                "quality_line",
                bitrate=stats.bitrate_kbps,
                loss=stats.loss_percent,
                jitter=stats.jitter_ms,
            )
        )
        self._quality_detail_label.setText(
            tr(
                "quality_detail",
                buffer=stats.buffer_ms,
                packets=stats.packets,
                lost=stats.lost,
            )
        )

    def _reset_quality_labels(self) -> None:
        self._quality_label.setText(tr("quality_idle"))
        self._quality_detail_label.setText("")

    # ------------------------------------------------------------- signals

    def _append_log(self, message: str) -> None:
        self._log.append(message)

    def _on_device_connected(self, ip: str, name: str) -> None:
        self._status_label.setText(tr("status_connected", name=name, ip=ip))
        self._append_log(tr("log_device_connected", name=name, ip=ip))

    def _on_device_disconnected(self, ip: str) -> None:
        self._status_label.setText(tr("status_waiting"))
        self._append_log(tr("log_device_disconnected", ip=ip))

    def _on_pairing_request(self, ip: str, pin: str) -> None:
        self._status_label.setText(tr("status_pairing", pin=pin))
        self._append_log(tr("log_pairing_request", ip=ip, pin=pin))

    def _on_gain_changed(self, value: int) -> None:
        # value is 0-500, represents percentage
        self._bridge.gain = value / 100.0
        self._gain_label.setText(f"{value}%")

    def _on_noise_suppression_toggled(self, checked: bool) -> None:
        self._bridge.noise_suppression_enabled = checked

    def _on_autostart_toggled(self, checked: bool) -> None:
        try:
            desktop_entry.set_autostart_enabled(checked)
        except OSError as exc:
            _log.warning("Could not update autostart entry: %s", exc)
            self._append_log(tr("error_autostart", error=exc))

    # ------------------------------------------------------------------ tray

    def _setup_tray_icon(self) -> None:
        # Not every compositor implements the systray protocol (some minimal
        # Wayland setups don't) — fall back to the plain "closing quits"
        # behavior instead of hiding the window into a tray icon nobody can
        # see or click.
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return

        QApplication.instance().setQuitOnLastWindowClosed(False)

        tray = QSystemTrayIcon(QIcon(str(desktop_entry.ICON_PATH)), self)
        tray.setToolTip("OpenMic")

        menu = QMenu()
        show_action = menu.addAction(tr("tray_show"))
        show_action.triggered.connect(self._show_from_tray)
        menu.addSeparator()
        quit_action = menu.addAction(tr("tray_quit"))
        quit_action.triggered.connect(self._quit)
        tray.setContextMenu(menu)

        tray.activated.connect(self._on_tray_activated)
        tray.show()
        self._tray = tray

    def _on_tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._show_from_tray()

    def _show_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _quit(self) -> None:
        self._stop_server()
        if self._tray is not None:
            self._tray.hide()
        QApplication.instance().quit()

    # --------------------------------------------------------------- devices

    def _refresh_device_list(self) -> None:
        self._devices_list.clear()
        for device in self._pairing_store.list_all():
            item = QListWidgetItem(f"{device['name']} ({device['device_id'][:8]}...)")
            item.setData(Qt.UserRole, device["device_id"])
            self._devices_list.addItem(item)
        self._unpair_all_button.setEnabled(self._devices_list.count() > 0)

    def _on_device_selection_changed(self) -> None:
        self._unpair_button.setEnabled(len(self._devices_list.selectedItems()) > 0)

    def _unpair_selected(self) -> None:
        for item in self._devices_list.selectedItems():
            device_id_hex = item.data(Qt.UserRole)
            name = item.text().split(" (")[0]
            self._pairing_store.remove(bytes.fromhex(device_id_hex))
            _log.info("Unpaired device: %s (%s...)", name, device_id_hex[:8])
            self._append_log(tr("log_unpaired", name=name))
        self._refresh_device_list()

    def _unpair_all(self) -> None:
        reply = QMessageBox.question(
            self,
            tr("confirm_title"),
            tr("confirm_unpair_all"),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        for device in self._pairing_store.list_all():
            self._pairing_store.remove(bytes.fromhex(device["device_id"]))
        self._append_log(tr("log_unpaired_all"))
        self._refresh_device_list()

    def closeEvent(self, event) -> None:
        if self._tray is not None:
            # Minimize to tray instead of quitting — the server (and the
            # phone's connection) should survive the window being closed.
            event.ignore()
            self.hide()
            self._tray.showMessage(
                "OpenMic",
                tr("tray_minimized"),
                QSystemTrayIcon.MessageIcon.Information,
                3000,
            )
            return
        self._stop_server()
        super().closeEvent(event)


def main() -> None:
    app = QApplication(sys.argv)
    desktop_entry.install_launcher_entry()
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
