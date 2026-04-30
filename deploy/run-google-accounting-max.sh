#!/bin/bash
# Запуск из каталога репозитория: .../deploy/run-google-accounting-max.sh
set -euo pipefail
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
ROOT_DIR=$(cd "$SCRIPT_DIR/.." && pwd)
cd "$ROOT_DIR"
export PYTHONUNBUFFERED=1

GIT_REV=$(git -C "$ROOT_DIR" rev-parse --short HEAD 2>/dev/null || echo "?")
echo "$(date -Is) google-accounting-max start cwd=$ROOT_DIR git=$GIT_REV" >&2

PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
if [ ! -x "$PYTHON_BIN" ]; then
	echo "ERROR: нет $PYTHON_BIN — создайте venv:" >&2
	echo "  cd $ROOT_DIR && python3 -m venv .venv && .venv/bin/pip install -U pip && .venv/bin/pip install -r requirements.txt" >&2
	exit 1
fi
exec "$PYTHON_BIN" "$ROOT_DIR/run.py"
