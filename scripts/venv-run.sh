#!/usr/bin/env bash
# Run any command inside the project venv.
# Usage: scripts/venv-run.sh python3 -c "import voice_io"
#        scripts/venv-run.sh pip install foo
#        scripts/venv-run.sh pytest tests/
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"

if [ ! -d "$VENV_DIR" ]; then
    echo "No venv found. Run scripts/setup.sh first."
    exit 1
fi

export PATH="$VENV_DIR/bin:$PATH"
exec "$@"
