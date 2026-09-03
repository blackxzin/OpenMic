#!/bin/bash
# Builds desktop/dist/openmic_<version>_amd64.deb from the current source tree.
#
# Same PyInstaller bundle as the AppImage, laid out as a Debian package for
# people who would rather have the app in their package manager (and get the
# launcher entry and dependency checks that come with it).
set -euo pipefail

DESKTOP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DESKTOP_DIR"

VENV_PY=".venv/bin/python"
VENV_PIP=".venv/bin/pip"
VENV_PYINSTALLER=".venv/bin/pyinstaller"

if [ ! -x "$VENV_PY" ]; then
    echo "error: $VENV_PY not found — run 'python3 -m venv .venv && .venv/bin/pip install -r requirements.txt' first" >&2
    exit 1
fi

if ! command -v dpkg-deb >/dev/null 2>&1; then
    echo "error: dpkg-deb not found — install dpkg (it exists for non-Debian distros too)" >&2
    exit 1
fi

if ! "$VENV_PY" -c "import PyInstaller" 2>/dev/null; then
    echo "Installing PyInstaller..."
    "$VENV_PIP" install pyinstaller -q
fi

VERSION="$("$VENV_PY" -c 'import openmic; print(openmic.__version__)')"
PKG_DIR="build/deb/openmic_${VERSION}_amd64"

echo "Bundling with PyInstaller..."
rm -rf build/deb dist/OpenMic OpenMic.spec
"$VENV_PYINSTALLER" --name OpenMic --onedir --windowed --noconfirm main.py

echo "Assembling package tree..."
install -d "$PKG_DIR/DEBIAN"
install -d "$PKG_DIR/opt/openmic"
install -d "$PKG_DIR/usr/bin"
install -d "$PKG_DIR/usr/share/applications"
install -d "$PKG_DIR/usr/share/icons/hicolor/256x256/apps"

cp -r dist/OpenMic/. "$PKG_DIR/opt/openmic/"
ln -s /opt/openmic/OpenMic "$PKG_DIR/usr/bin/openmic"
install -m 644 packaging/appimage/openmic.png \
    "$PKG_DIR/usr/share/icons/hicolor/256x256/apps/openmic.png"

cat > "$PKG_DIR/usr/share/applications/openmic.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=OpenMic
Comment=Use your phone as a wireless microphone
Exec=/usr/bin/openmic
Icon=openmic
Categories=AudioVideo;Audio;
Terminal=false
DESKTOP

# libopus0 and libportaudio2 are dlopen'd by name at runtime (opuslib and
# sounddevice), so the package manager has to guarantee them — PyInstaller
# can't see those imports. pulseaudio-utils provides pactl, which is how the
# virtual microphone is created.
cat > "$PKG_DIR/DEBIAN/control" <<CONTROL
Package: openmic
Version: ${VERSION}
Section: sound
Priority: optional
Architecture: amd64
Depends: libopus0, libportaudio2, pulseaudio-utils
Maintainer: OpenMic contributors
Description: Use your phone as a wireless microphone
 Creates a virtual microphone on Linux and streams audio to it from the
 OpenMic app on an Android phone or iPhone over the local WiFi network.
CONTROL

echo "Building .deb..."
mkdir -p dist
dpkg-deb --build --root-owner-group "$PKG_DIR" "dist/openmic_${VERSION}_amd64.deb"

rm -rf build/deb OpenMic.spec

echo "Done: dist/openmic_${VERSION}_amd64.deb"
