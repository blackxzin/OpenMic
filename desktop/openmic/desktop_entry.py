"""Launcher and autostart .desktop entries for the desktop app.

Everything here regenerates paths at runtime instead of hardcoding an install
location, because the same code runs from a git checkout, from a raw
PyInstaller binary, and from inside an AppImage — and only one of those has
paths that survive the process exiting.
"""

import logging
import os
import sys
from pathlib import Path

_log = logging.getLogger(__name__)

APP_DIR = Path(__file__).resolve().parent.parent

DESKTOP_ENTRY_NAME = "openmic.desktop"
AUTOSTART_DIR = Path.home() / ".config" / "autostart"
APPLICATIONS_DIR = Path.home() / ".local" / "share" / "applications"
ICONS_DIR = Path.home() / ".local" / "share" / "icons"
INSTALLED_ICON_PATH = ICONS_DIR / "openmic.png"


def resolve_icon_path() -> Path:
    # Running from source, the icon sits next to main.py. Running from the
    # AppImage, main.py is frozen by PyInstaller and that relative path
    # doesn't exist in the bundle — but the AppImage runtime sets $APPDIR to
    # the mount point, and build_appimage.sh copies openmic.png there
    # (alongside AppRun), so that's where it actually lives at runtime.
    appdir = os.environ.get("APPDIR")
    if appdir:
        candidate = Path(appdir) / "openmic.png"
        if candidate.exists():
            return candidate
    return APP_DIR / "packaging" / "appimage" / "openmic.png"


ICON_PATH = resolve_icon_path()


def ensure_icon_installed() -> None:
    """Copy the icon to a location that outlives this process.

    Referencing ICON_PATH directly in a .desktop file works for the source/
    venv case (a stable repo path) but breaks for the AppImage case, where it
    points inside the squashfs mount that's unmounted the moment this process
    exits — the very next click on the launcher entry would show a blank
    icon. Copying once to a persistent path sidesteps that regardless of how
    this run was launched.
    """
    if INSTALLED_ICON_PATH.exists() or not ICON_PATH.exists():
        return
    ICONS_DIR.mkdir(parents=True, exist_ok=True)
    INSTALLED_ICON_PATH.write_bytes(ICON_PATH.read_bytes())


def executable_command() -> str:
    """The command that reopens this exact install, however it was launched.

    - Inside an AppImage, sys.executable is the PyInstaller binary under the
      squashfs mount point — that mount is torn down when this process
      exits, so a launcher entry pointing at it would dangle immediately.
      $APPIMAGE (set by the AppImage runtime) is the actual .AppImage file
      path and stays valid.
    - A raw PyInstaller build run directly (no AppImage wrapper): sys.frozen
      is set and sys.executable is the real, persistent binary.
    - Running from source: venv python + main.py's path.
    """
    appimage_path = os.environ.get("APPIMAGE")
    if appimage_path:
        return appimage_path
    if getattr(sys, "frozen", False):
        return sys.executable
    return f"{sys.executable} {APP_DIR / 'main.py'}"


def entry_contents() -> str:
    lines = [
        "[Desktop Entry]",
        "Type=Application",
        "Name=OpenMic",
        "Comment=Use your phone as a wireless microphone",
        f"Exec={executable_command()}",
        f"Icon={INSTALLED_ICON_PATH}",
    ]
    if "APPIMAGE" not in os.environ:
        # Meaningless for the AppImage case: that mount point is gone the
        # moment this process exits, and $APPIMAGE re-mounts fresh anyway.
        lines.append(f"Path={APP_DIR}")
    lines += ["Categories=AudioVideo;Audio;", "Terminal=false", ""]
    return "\n".join(lines)


def install_launcher_entry() -> None:
    """Write the .desktop file so the app shows up in the OS app launcher.

    Best-effort and silent: a missing/unwritable applications dir shouldn't
    block the app from starting, it just means no launcher entry.
    """
    try:
        ensure_icon_installed()
        APPLICATIONS_DIR.mkdir(parents=True, exist_ok=True)
        (APPLICATIONS_DIR / DESKTOP_ENTRY_NAME).write_text(entry_contents())
    except OSError as exc:
        _log.warning("Could not install launcher entry: %s", exc)


def autostart_entry_path() -> Path:
    return AUTOSTART_DIR / DESKTOP_ENTRY_NAME


def is_autostart_enabled() -> bool:
    return autostart_entry_path().exists()


def set_autostart_enabled(enabled: bool) -> None:
    path = autostart_entry_path()
    if enabled:
        ensure_icon_installed()
        AUTOSTART_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(entry_contents() + "X-GNOME-Autostart-enabled=true\n")
    else:
        path.unlink(missing_ok=True)
