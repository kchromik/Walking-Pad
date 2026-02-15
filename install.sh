#!/bin/bash
set -e
cd "$(dirname "$0")"

echo "WalkingPad OBS Overlay — Installer"
echo "===================================="

# Check tkinter
python3 -c "import tkinter" 2>/dev/null || {
    echo "tkinter nicht gefunden. Installiere mit:"
    echo "  paru -S tk"
    exit 1
}

# Create venv if needed
if [ ! -d .venv ]; then
    echo "Erstelle Python venv..."
    python3 -m venv .venv
fi

# Install dependencies
echo "Installiere Dependencies..."
.venv/bin/pip install -q -r requirements.txt

# Make start.sh executable
chmod +x start.sh

# Install desktop entry
echo "Installiere Desktop-Entry..."
cp walkingpad-obs.desktop ~/.local/share/applications/
update-desktop-database ~/.local/share/applications/ 2>/dev/null || true

echo ""
echo "Fertig! Du kannst WalkingPad Control jetzt:"
echo "  1. Im Startmenü finden (evtl. neu einloggen)"
echo "  2. Oder direkt starten: ./start.sh"
