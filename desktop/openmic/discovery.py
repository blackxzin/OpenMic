"""Advertises the desktop server on the local network via mDNS so the phone
app can find it without the user typing an IP address."""

import socket
from typing import Optional

from zeroconf import ServiceInfo, Zeroconf

SERVICE_TYPE = "_openmic._udp.local."


class ServiceAdvertiser:
    def __init__(self):
        self._zeroconf: Optional[Zeroconf] = None
        self._info: Optional[ServiceInfo] = None

    def start(self, port: int, ip: str) -> None:
        if self._zeroconf is not None:
            return
        hostname = socket.gethostname()
        self._info = ServiceInfo(
            SERVICE_TYPE,
            f"OpenMic on {hostname}.{SERVICE_TYPE}",
            port=port,
            parsed_addresses=[ip],
            server=f"{hostname}.local.",
        )
        self._zeroconf = Zeroconf()
        self._zeroconf.register_service(self._info, allow_name_change=True)

    def stop(self) -> None:
        if self._zeroconf is not None and self._info is not None:
            self._zeroconf.unregister_service(self._info)
            self._zeroconf.close()
        self._zeroconf = None
        self._info = None
