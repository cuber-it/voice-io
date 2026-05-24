#!/usr/bin/env bash
# Setup venv and install dependencies
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"

echo "=== voice-io setup ==="

# System deps check
for cmd in python3 pip3; do
    if ! command -v "$cmd" &>/dev/null; then
        echo "ERROR: $cmd not found"
        exit 1
    fi
done

# Check libportaudio
if ! ldconfig -p 2>/dev/null | grep -q libportaudio; then
    echo "WARNING: libportaudio not found. Install with: sudo apt install libportaudio2"
fi

# Create venv if missing
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating venv in $VENV_DIR ..."
    python3 -m venv "$VENV_DIR"
fi

# Activate and install
source "$VENV_DIR/bin/activate"
pip install --upgrade pip -q
pip install -r "$PROJECT_DIR/requirements.txt"
pip install -e "$PROJECT_DIR"

echo ""
echo "Done. Activate with:"
echo "  source $VENV_DIR/bin/activate"
