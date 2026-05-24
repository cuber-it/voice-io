#!/usr/bin/env bash
# Activate venv and drop into shell
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"

if [ ! -d "$VENV_DIR" ]; then
    echo "No venv found. Run scripts/setup.sh first."
    exit 1
fi

source "$VENV_DIR/bin/activate"
echo "voice-io venv active. Python: $(python3 --version)"
exec "$SHELL"
