#!/bin/sh

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$SCRIPT_DIR" || exit 1

PY_EXE=""
PY_LABEL=""
TARGET_PY="$SCRIPT_DIR/show_serve_file_counts.py"

if command -v python3 >/dev/null 2>&1; then
    PY_EXE=$(command -v python3)
    PY_LABEL="python3"
elif command -v python >/dev/null 2>&1; then
    PY_EXE=$(command -v python)
    PY_LABEL="python"
else
    echo "[ERROR] Python was not found."
    echo "[ERROR] Install python3/python and add it to PATH first."
    exit 1
fi

if [ ! -f "$TARGET_PY" ]; then
    echo "[ERROR] show_serve_file_counts.py was not found: $TARGET_PY"
    exit 1
fi

echo "[INFO] Using Python: $PY_LABEL"
echo "[INFO] Entry: show_serve_file_counts.py"
if [ -f "$SCRIPT_DIR/requirements.txt" ]; then
    echo "[INFO] Installing requirements.txt with global Python"
    "$PY_EXE" -m pip --version >/dev/null 2>&1 || "$PY_EXE" -m ensurepip --upgrade >/dev/null 2>&1 || true
    "$PY_EXE" -m pip install -r "$SCRIPT_DIR/requirements.txt" || exit 1
fi

exec "$PY_EXE" "$TARGET_PY" "$@"
