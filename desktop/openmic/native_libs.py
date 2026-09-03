"""Resolve C libraries that Python loads by name at runtime.

opuslib does ``find_library('opus')`` at import time and raises if it comes
back empty — so on a machine without libopus installed, importing it takes
the whole app down before the window ever appears. find_library only
consults the system library cache, which means a copy shipped inside a
PyInstaller bundle/AppImage is invisible to it no matter what
LD_LIBRARY_PATH says.

This module makes the bundled copy discoverable for the duration of an
import, and is a no-op when running from source against system libraries.
"""

import ctypes.util
import logging
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

_log = logging.getLogger(__name__)


def bundled_library_dir() -> Optional[Path]:
    """Directory holding libraries shipped alongside a frozen build."""
    if not getattr(sys, "frozen", False):
        return None
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return Path(sys.executable).resolve().parent


def find_bundled_library(name: str, directory: Optional[Path] = None) -> Optional[str]:
    """Path to ``lib<name>.so*`` inside the bundle, if it ships one."""
    library_dir = bundled_library_dir() if directory is None else directory
    if library_dir is None or not library_dir.is_dir():
        return None
    matches = sorted(library_dir.glob(f"lib{name}.so*"))
    return str(matches[0]) if matches else None


@contextmanager
def library_fallback(*names: str) -> Iterator[None]:
    """Let ``find_library`` see bundled copies of ``names`` inside this block.

    The system lookup still wins: a distro-installed library is preferred
    over the bundled one, which only fills in when nothing is installed.
    """
    original = ctypes.util.find_library

    def patched(name):
        found = original(name)
        if found is not None:
            return found
        if name in names:
            bundled = find_bundled_library(name)
            if bundled:
                _log.info("Using bundled %s: %s", name, bundled)
                return bundled
        return None

    ctypes.util.find_library = patched
    try:
        yield
    finally:
        ctypes.util.find_library = original
