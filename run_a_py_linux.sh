#!/bin/sh

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$SCRIPT_DIR" || exit 1

PY_EXE=""
PY_LABEL=""
TARGET_PY=""
TARGET_LABEL=""
BATCH_MODE=1

if [ "${1:-}" = "--single" ]; then
    BATCH_MODE=0
    shift
fi

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

if [ "$BATCH_MODE" -eq 1 ] && [ -f "$SCRIPT_DIR/run_from_serve_list.py" ] && [ -f "$SCRIPT_DIR/serve_list.csv" ]; then
    TARGET_PY="$SCRIPT_DIR/run_from_serve_list.py"
    TARGET_LABEL="run_from_serve_list.py"
elif [ -f "$SCRIPT_DIR/origin.py" ]; then
    TARGET_PY="$SCRIPT_DIR/origin.py"
    TARGET_LABEL="origin.py"
elif [ -f "$SCRIPT_DIR/run_a_py_parallel.py" ] && find "$SCRIPT_DIR" -maxdepth 1 -type f -name 'a*.py' | grep -q .; then
    TARGET_PY="$SCRIPT_DIR/run_a_py_parallel.py"
    TARGET_LABEL="run_a_py_parallel.py"
else
    echo "[ERROR] No runnable entry was found."
    echo "[ERROR] Expected run_from_serve_list.py + serve_list.csv, origin.py, or run_a_py_parallel.py with a*.py files."
    exit 1
fi

echo "[INFO] Using Python: $PY_LABEL"
echo "[INFO] Entry: $TARGET_LABEL"
if [ "$BATCH_MODE" -eq 1 ] && [ "$TARGET_LABEL" = "run_from_serve_list.py" ]; then
    echo "[INFO] Mode: batch (serve_list.csv)"
elif [ "$BATCH_MODE" -eq 0 ]; then
    echo "[INFO] Mode: single"
fi
if [ -f "$SCRIPT_DIR/requirements.txt" ]; then
    echo "[INFO] Installing requirements.txt with global Python"
    "$PY_EXE" -m pip --version >/dev/null 2>&1 || "$PY_EXE" -m ensurepip --upgrade >/dev/null 2>&1 || true
    "$PY_EXE" -m pip install -r "$SCRIPT_DIR/requirements.txt" || exit 1
fi

RUN_A_PY_LABEL="$PY_LABEL" exec "$PY_EXE" "$TARGET_PY" "$@"
