"""Tests for get_local_ips' virtual-interface filtering.

Docker/Podman/libvirt bridge networks show up in `ip addr` alongside the
real LAN interface but are never reachable from the phone — picking one as
the suggested "use this" address silently breaks connecting.
"""

import unittest
from unittest.mock import MagicMock, patch

from openmic.net_ifaces import get_local_ips, is_virtual_iface as _is_virtual_iface


class TestIsVirtualIface(unittest.TestCase):
    def test_real_interfaces_are_not_virtual(self):
        for name in ("enp6s0", "eth0", "wlan0", "wlp3s0"):
            self.assertFalse(_is_virtual_iface(name), name)

    def test_container_and_vm_bridges_are_virtual(self):
        for name in ("docker0", "br-0276c3b731da", "veth1234", "virbr0", "vmnet1", "podman0"):
            self.assertTrue(_is_virtual_iface(name), name)

    def test_vpn_interfaces_are_virtual(self):
        for name in ("tun0", "tap0"):
            self.assertTrue(_is_virtual_iface(name), name)


if __name__ == "__main__":
    unittest.main()


class TestGetLocalIps(unittest.TestCase):
    """`ip -4 -o addr show` parsing and ordering, without touching the host."""

    IP_OUTPUT = (
        "1: lo    inet 127.0.0.1/8 scope host lo\n"
        "2: enp6s0    inet 192.168.0.20/24 brd 192.168.0.255 scope global enp6s0\n"
        "3: wlp3s0    inet 192.168.0.42/24 brd 192.168.0.255 scope global wlp3s0\n"
        "4: docker0    inet 172.17.0.1/16 brd 172.17.255.255 scope global docker0\n"
    )

    def _run(self, stdout: str):
        result = MagicMock()
        result.stdout = stdout
        with patch("openmic.net_ifaces.subprocess.run", return_value=result):
            return get_local_ips()

    def test_wifi_address_comes_first(self):
        # The phone is on WiFi; a wired default route would be the wrong hint.
        self.assertEqual(self._run(self.IP_OUTPUT)[0], "192.168.0.42")

    def test_loopback_and_virtual_bridges_are_excluded(self):
        addresses = self._run(self.IP_OUTPUT)
        self.assertNotIn("127.0.0.1", addresses)
        self.assertNotIn("172.17.0.1", addresses)
        self.assertEqual(len(addresses), 2)

    def test_falls_back_to_a_udp_probe_when_ip_returns_nothing(self):
        with patch("openmic.net_ifaces.socket.socket") as fake_socket:
            probe = fake_socket.return_value.__enter__.return_value
            probe.getsockname.return_value = ("10.1.2.3", 51000)
            self.assertEqual(self._run(""), ["10.1.2.3"])

    def test_falls_back_to_loopback_when_everything_fails(self):
        with patch("openmic.net_ifaces.socket.socket", side_effect=OSError):
            self.assertEqual(self._run(""), ["127.0.0.1"])

    def test_a_missing_ip_command_does_not_raise(self):
        with patch("openmic.net_ifaces.subprocess.run", side_effect=FileNotFoundError), \
             patch("openmic.net_ifaces.socket.socket", side_effect=OSError):
            self.assertEqual(get_local_ips(), ["127.0.0.1"])
