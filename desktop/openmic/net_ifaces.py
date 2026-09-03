"""Which of this machine's IPv4 addresses the phone should be pointed at."""

import re
import socket
import subprocess

_IP_ADDR_LINE = re.compile(r"^\d+:\s+(\S+)\s+inet\s+(\d+\.\d+\.\d+\.\d+)")

# Virtual interfaces created by container/VM tooling never reach the phone —
# they're isolated bridge networks local to this machine (Docker, Podman,
# libvirt, VPNs). Surfacing one of these as the "use this" IP produces an
# address the phone can never connect to.
VIRTUAL_IFACE_PREFIXES = ("docker", "br-", "veth", "virbr", "vmnet", "podman", "tun", "tap")


def is_virtual_iface(name: str) -> bool:
    return name.startswith(VIRTUAL_IFACE_PREFIXES)


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
                if ip.startswith("127.") or is_virtual_iface(iface):
                    continue
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
