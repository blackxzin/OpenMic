#!/bin/bash
# Builds desktop/dist/OpenMic-x86_64.AppImage from the current source tree.
set -euo pipefail

DESKTOP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DESKTOP_DIR"

VENV_PY=".venv/bin/python"
VENV_PIP=".venv/bin/pip"
VENV_PYINSTALLER=".venv/bin/pyinstaller"
APPIMAGETOOL="build-tools/appimagetool"

if [ ! -x "$VENV_PY" ]; then
    echo "error: $VENV_PY not found — run 'python3 -m venv .venv && .venv/bin/pip install -r requirements.txt' first" >&2
    exit 1
fi

if ! "$VENV_PY" -c "import PyInstaller" 2>/dev/null; then
    echo "Installing PyInstaller..."
    "$VENV_PIP" install pyinstaller -q
fi

if [ ! -x "$APPIMAGETOOL" ]; then
    echo "Downloading appimagetool..."
    mkdir -p build-tools
    curl -L -o "$APPIMAGETOOL" \
        "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"
    chmod +x "$APPIMAGETOOL"
fi

echo "Bundling with PyInstaller..."
rm -rf build dist OpenMic.spec
"$VENV_PYINSTALLER" --name OpenMic --onedir --windowed --noconfirm main.py

echo "Assembling AppDir..."
rm -rf AppDir
mkdir -p AppDir/usr/bin
cp -r dist/OpenMic/* AppDir/usr/bin/
cp packaging/appimage/AppRun AppDir/AppRun
cp packaging/appimage/openmic.desktop AppDir/openmic.desktop
cp packaging/appimage/openmic.png AppDir/openmic.png
chmod +x AppDir/AppRun

echo "Building AppImage..."
mkdir -p dist
ARCH=x86_64 "$APPIMAGETOOL" AppDir dist/OpenMic-x86_64.AppImage

rm -rf AppDir build OpenMic.spec

echo "Done: dist/OpenMic-x86_64.AppImage"
