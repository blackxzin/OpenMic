"""Creates a virtual microphone on Linux via PipeWire's PulseAudio compatibility layer.

A null-sink receives the playback audio we write to it, and a remap-source
exposes that sink's monitor as a regular input device other apps can pick.
"""

import subprocess

SINK_NAME = "OpenMicSink"
SOURCE_NAME = "OpenMic_Microphone"


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
        self._sink_module_id = self._load_module(
            "module-null-sink",
            f"sink_name={SINK_NAME}",
            f"sink_properties=device.description={SINK_NAME}",
        )
        try:
            self._source_module_id = self._load_module(
                "module-remap-source",
                f"master={SINK_NAME}.monitor",
                f"source_name={SOURCE_NAME}",
                "source_properties=device.description=OpenMic_Microphone",
            )
        except VirtualMicError:
            self._unload_module(self._sink_module_id)
            self._sink_module_id = None
            raise

    def destroy(self) -> None:
        if self._source_module_id is not None:
            self._unload_module(self._source_module_id)
            self._source_module_id = None
        if self._sink_module_id is not None:
            self._unload_module(self._sink_module_id)
            self._sink_module_id = None

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
