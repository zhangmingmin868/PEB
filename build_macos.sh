#!/bin/bash
# ------------------------------------------------------------------
#  Build LabDream Version 1.0 for macOS  ->  dist/LabDream.app
#  Usage:  ./build_macos.sh
# ------------------------------------------------------------------
set -e
cd "$(dirname "$0")"

if [ ! -d .venv-build ]; then
    echo "Creating build environment..."
    python3 -m venv .venv-build
fi

echo "Installing dependencies..."
.venv-build/bin/python -m pip install --upgrade pip >/dev/null
.venv-build/bin/pip install -r requirements.txt pyinstaller

echo "Building LabDream.app ..."
.venv-build/bin/pyinstaller --noconfirm --clean labdream.spec

echo
echo "Done: $(pwd)/dist/LabDream.app"
