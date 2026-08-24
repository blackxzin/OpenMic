"""Tests for VirtualMic's stale-module detection.

pactl modules outlive our process. If a null-sink/remap-source pair was
loaded by an older build (before the mono channel fix), create() must not
silently reuse it — that reintroduces the "no audio" bug the mono config
exists to prevent (see virtual_mic.py's create()).
"""

import unittest
from unittest.mock import patch

from openmic.virtual_mic import SINK_NAME, SOURCE_NAME, VirtualMic


def _pactl_short_line(module_id: int, module_type: str, args: str) -> str:
    return f"{module_id}\t{module_type}\t{args}"


class FakePactl:
    """Fakes the subset of `pactl` behavior VirtualMic.create() depends on."""

    def __init__(self, initial_modules: dict[int, tuple[str, str]]):
        self.modules = dict(initial_modules)  # id -> (type, args)
        self._next_id = max(self.modules, default=0) + 1
        self.default_sink = "AlsaSpeakers"
        self.load_calls: list[tuple[str, ...]] = []
        self.volume_calls: list[tuple[str, ...]] = []

    def run(self, cmd, **kwargs):
        result = unittest.mock.Mock()
        result.returncode = 0
        result.stderr = ""

        if cmd[:3] == ["pactl", "list", "modules"]:
            result.stdout = "\n".join(
                _pactl_short_line(mid, mtype, args)
                for mid, (mtype, args) in self.modules.items()
            )
        elif cmd[:2] == ["pactl", "load-module"]:
            module_type = cmd[2]
            args = " ".join(cmd[3:])
            self.load_calls.append(tuple(cmd[2:]))
            mid = self._next_id
            self._next_id += 1
            self.modules[mid] = (module_type, args)
            result.stdout = str(mid)
        elif cmd[:2] == ["pactl", "unload-module"]:
            self.modules.pop(int(cmd[2]), None)
            result.stdout = ""
        elif cmd[:2] == ["pactl", "get-default-sink"]:
            result.stdout = self.default_sink
        elif cmd[:2] == ["pactl", "set-default-sink"]:
            self.default_sink = cmd[2]
            result.stdout = ""
        elif cmd[0] == "pactl" and cmd[1] in (
            "set-sink-mute",
            "set-sink-volume",
            "set-source-mute",
            "set-source-volume",
        ):
            self.volume_calls.append(tuple(cmd[1:]))
            result.stdout = ""
        else:
            raise AssertionError(f"unexpected pactl invocation: {cmd}")

        return result


class TestVirtualMicStaleModules(unittest.TestCase):
    def _run_create(self, fake: FakePactl) -> VirtualMic:
        vm = VirtualMic()
        with patch("openmic.virtual_mic.subprocess.run", side_effect=fake.run):
            vm.create()
        return vm

    def test_fresh_environment_creates_mono_sink_and_source(self):
        fake = FakePactl({})
        vm = self._run_create(fake)

        sink_args = fake.modules[vm._sink_module_id][1]
        source_args = fake.modules[vm._source_module_id][1]
        self.assertIn("channels=1", sink_args)
        self.assertIn("channel_map=mono", sink_args)
        self.assertIn("channels=1", source_args)
        self.assertIn("channel_map=mono", source_args)

    def test_stale_stereo_sink_is_recreated_not_reused(self):
        # Simulates a sink/source left loaded by a pre-mono-fix build.
        fake = FakePactl(
            {
                1: ("module-null-sink", f"sink_name={SINK_NAME} sink_properties=device.description={SINK_NAME}"),
                2: ("module-remap-source", f"master={SINK_NAME}.monitor source_name={SOURCE_NAME}"),
            }
        )
        vm = self._run_create(fake)

        # Old stale modules must be gone, not left dangling alongside new ones.
        self.assertNotIn(1, fake.modules)
        self.assertNotIn(2, fake.modules)

        sink_args = fake.modules[vm._sink_module_id][1]
        source_args = fake.modules[vm._source_module_id][1]
        self.assertIn("channels=1", sink_args)
        self.assertIn("channel_map=mono", source_args)

    def test_correctly_configured_modules_are_reused_without_reload(self):
        fake = FakePactl(
            {
                7: (
                    "module-null-sink",
                    f"sink_name={SINK_NAME} sink_properties=device.description={SINK_NAME} channels=1 channel_map=mono",
                ),
                8: (
                    "module-remap-source",
                    f"master={SINK_NAME}.monitor source_name={SOURCE_NAME} "
                    "source_properties=device.description=OpenMic_Microphone channels=1 channel_map=mono",
                ),
            }
        )
        vm = self._run_create(fake)

        self.assertEqual(vm._sink_module_id, 7)
        self.assertEqual(vm._source_module_id, 8)
        self.assertEqual(fake.load_calls, [])  # nothing recreated

    def test_create_always_unmutes_and_resets_volume_to_unity(self):
        # module-stream-restore persists volume per device name across reloads —
        # a source/sink turned down once (by another app, or a leftover restore
        # entry) stays quiet on every future create() otherwise: audio flows
        # through the whole pipeline with no error and just never gets heard.
        fake = FakePactl({})
        self._run_create(fake)

        self.assertIn(("set-sink-mute", SINK_NAME, "0"), fake.volume_calls)
        self.assertIn(("set-sink-volume", SINK_NAME, "100%"), fake.volume_calls)
        self.assertIn(("set-source-mute", SOURCE_NAME, "0"), fake.volume_calls)
        self.assertIn(("set-source-volume", SOURCE_NAME, "100%"), fake.volume_calls)

    def test_stale_sink_forces_source_recreation_even_if_source_args_look_fine(self):
        # Source already has correct channel args, but its master points at a
        # sink module that create() is about to tear down and replace — reusing
        # it would attach the source to a dead master.
        fake = FakePactl(
            {
                3: ("module-null-sink", f"sink_name={SINK_NAME} sink_properties=device.description={SINK_NAME}"),
                4: (
                    "module-remap-source",
                    f"master={SINK_NAME}.monitor source_name={SOURCE_NAME} channels=1 channel_map=mono",
                ),
            }
        )
        vm = self._run_create(fake)

        self.assertNotIn(3, fake.modules)
        self.assertNotIn(4, fake.modules)
        self.assertNotEqual(vm._sink_module_id, 3)
        self.assertNotEqual(vm._source_module_id, 4)


if __name__ == "__main__":
    unittest.main()
