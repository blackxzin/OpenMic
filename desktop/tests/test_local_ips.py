"""Tests for main.get_local_ips' virtual-interface filtering.

Docker/Podman/libvirt bridge networks show up in `ip addr` alongside the
real LAN interface but are never reachable from the phone — picking one as
the suggested "use this" address silently breaks connecting.
"""

import unittest

from main import _is_virtual_iface


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
