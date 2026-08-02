"""Creates a virtual microphone on Linux via PipeWire's PulseAudio compatibility layer.

A null-sink receives the playback audio we write to it, and a remap-source
exposes that sink's monitor as a regular input device other apps can pick.
"""

import logging
import subprocess

SINK_NAME = "OpenMicSink"
SOURCE_NAME = "OpenMic_Microphone"

_log = logging.getLogger(__name__)


class VirtualMicError(RuntimeError):
    pass


class VirtualMic:
    def __init__(self):
        self._sink_module_id: int | None = None
        self._source_module_id: int | None = None

    @property
    def is_loaded(self) -> bool:
        return self._sink_module_id is not None

    def create(self) -> None:
        if self.is_loaded:
            return

        # Check if modules already exist (e.g., from a previous unclean shutdown)
        existing_sink = self._find_module("module-null-sink", f"sink_name={SINK_NAME}")
        existing_source = self._find_module("module-remap-source", f"source_name={SOURCE_NAME}")

        if existing_sink is not None:
            _log.info("Sink already exists (module %d), reusing", existing_sink)
            self._sink_module_id = existing_sink
        else:
            self._sink_module_id = self._load_module(
                "module-null-sink",
                f"sink_name={SINK_NAME}",
                f"sink_properties=device.description={SINK_NAME}",
            )
            _log.info("Created sink (module %d)", self._sink_module_id)

        if existing_source is not None:
            _log.info("Source already exists (module %d), reusing", existing_source)
            self._source_module_id = existing_source
        else:
            try:
                self._source_module_id = self._load_module(
                    "module-remap-source",
                    f"master={SINK_NAME}.monitor",
                    f"source_name={SOURCE_NAME}",
                    "source_properties=device.description=OpenMic_Microphone",
                )
                _log.info("Created source (module %d)", self._source_module_id)
            except VirtualMicError:
                if existing_sink is None:
                    self._unload_module(self._sink_module_id)
                self._sink_module_id = None
                raise

    def destroy(self) -> None:
        if self._source_module_id is not None:
            self._unload_module(self._source_module_id)
            _log.info("Destroyed source (module %d)", self._source_module_id)
            self._source_module_id = None
        if self._sink_module_id is not None:
            self._unload_module(self._sink_module_id)
            _log.info("Destroyed sink (module %d)", self._sink_module_id)
            self._sink_module_id = None

    @staticmethod
    def _find_module(module_type: str, arg: str) -> int | None:
        """Return module ID if already loaded, else None."""
        result = subprocess.run(
            ["pactl", "list", "modules", "short"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return None
        for line in result.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) >= 2 and parts[1] == module_type and arg in parts[1]:
                try:
                    return int(parts[0])
                except ValueError:
                    pass
        return None

    @staticmethod
    def _load_module(module: str, *args: str) -> int:
        result = subprocess.run(
            ["pactl", "load-module", module, *args],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise VirtualMicError(result.stderr.strip() or f"failed to load {module}")
        return int(result.stdout.strip())

    @staticmethod
    def _unload_module(module_id: int) -> None:
        subprocess.run(["pactl", "unload-module", str(module_id)], capture_output=True, text=True)
