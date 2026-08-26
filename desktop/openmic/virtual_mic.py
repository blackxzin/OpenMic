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

        # PipeWire/WirePlumber can auto-switch the system's default output to
        # a newly created sink. If that happens here, every app's playback
        # (browser, music, notifications) gets mixed into OpenMicSink and
        # then picked up by OpenMic_Microphone as "microphone" audio — heard
        # by the other end as system noise instead of just the phone's voice.
        # Snapshot the real default now and restore it once we're done, so
        # creating our sink never silently hijacks the user's speakers.
        previous_default_sink = self._get_default_sink()

        # Check if modules already exist (e.g., from a previous unclean shutdown,
        # or a still-loaded module from before mono config was added below).
        # pactl modules outlive our process, so a stale stereo sink/source from
        # an older run can still be sitting there — reusing it as-is would silently
        # bring back the "no audio" bug the mono config exists to prevent.
        existing_sink = self._find_module("module-null-sink", f"sink_name={SINK_NAME}")
        if existing_sink is not None and not self._module_has_args(existing_sink, "channels=1", "channel_map=mono"):
            _log.info("Stale sink (module %d) has outdated channel config, recreating", existing_sink)
            self._unload_module(existing_sink)
            existing_sink = None

        sink_was_recreated = existing_sink is None

        existing_source = self._find_module("module-remap-source", f"source_name={SOURCE_NAME}")
        if existing_source is not None and (
            sink_was_recreated
            or not self._module_has_args(existing_source, "channels=1", "channel_map=mono")
        ):
            # sink_was_recreated: even a source with correct args still points at
            # master=<old sink id>.monitor, which no longer exists once the sink
            # above was torn down — reuse would attach to a dead master.
            _log.info("Stale source (module %d) needs recreating", existing_source)
            self._unload_module(existing_source)
            existing_source = None

        if existing_sink is not None:
            _log.info("Sink already exists (module %d), reusing", existing_sink)
            self._sink_module_id = existing_sink
        else:
            self._sink_module_id = self._load_module(
                "module-null-sink",
                f"sink_name={SINK_NAME}",
                f"sink_properties=device.description={SINK_NAME}",
                # We only ever write mono PCM into this sink (see server.py's
                # AudioBridge). A stereo sink would leave the right channel
                # permanently silent, and apps that don't fall back to a
                # sane mono downmix (observed with Discord/WebRTC) end up
                # producing no audio at all instead of just half-volume.
                "channels=1",
                "channel_map=mono",
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
                    # Without an explicit channel map, module-remap-source
                    # upmixes the mono master back to stereo on its own,
                    # reintroducing the silent-second-channel problem the
                    # mono sink above was meant to avoid.
                    "channels=1",
                    "channel_map=mono",
                )
                _log.info("Created source (module %d)", self._source_module_id)
            except VirtualMicError:
                if existing_sink is None:
                    self._unload_module(self._sink_module_id)
                self._sink_module_id = None
                raise

        # module-stream-restore remembers a volume per device *name* across
        # module reloads. Once anything (another app, an accidental scroll on
        # a volume slider) ever turns OpenMic_Microphone down, every future
        # create() silently inherits that low volume — audio flows through
        # the whole pipeline correctly but comes out near-silent with no
        # error anywhere. Force it back to unity every time so that stale
        # restored volume can never reintroduce the "no audio" bug.
        self._unmute_and_reset_volume("sink", SINK_NAME)
        self._unmute_and_reset_volume("source", SOURCE_NAME)

        if previous_default_sink and previous_default_sink != SINK_NAME:
            self._set_default_sink(previous_default_sink)

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
            if len(parts) >= 2 and parts[1] == module_type and arg in line:
                try:
                    return int(parts[0])
                except ValueError:
                    pass
        return None

    @staticmethod
    def _module_has_args(module_id: int, *required_args: str) -> bool:
        """Check whether a loaded module's argument line contains every given substring."""
        result = subprocess.run(
            ["pactl", "list", "modules", "short"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return False
        for line in result.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) >= 1 and parts[0] == str(module_id):
                return all(arg in line for arg in required_args)
        return False

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

    @staticmethod
    def _get_default_sink() -> str | None:
        result = subprocess.run(
            ["pactl", "get-default-sink"], capture_output=True, text=True
        )
        if result.returncode != 0:
            return None
        name = result.stdout.strip()
        return name or None

    @staticmethod
    def _set_default_sink(name: str) -> None:
        subprocess.run(["pactl", "set-default-sink", name], capture_output=True, text=True)

    @staticmethod
    def _unmute_and_reset_volume(kind: str, name: str) -> None:
        subprocess.run(["pactl", f"set-{kind}-mute", name, "0"], capture_output=True, text=True)
        subprocess.run(["pactl", f"set-{kind}-volume", name, "100%"], capture_output=True, text=True)
