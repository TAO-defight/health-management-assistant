#!/bin/sh
set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PYTHON_BIN=${PYTHON_BIN:-python3}
BUNDLED_PYTHON=/Users/tao/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3

if ! "$PYTHON_BIN" -c "import reportlab" >/dev/null 2>&1 && [ -x "$BUNDLED_PYTHON" ]; then
  PYTHON_BIN=$BUNDLED_PYTHON
fi

exec "$PYTHON_BIN" "$PROJECT_DIR/app.py"
