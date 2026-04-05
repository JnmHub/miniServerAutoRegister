#!/bin/sh

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$SCRIPT_DIR" || exit 1

PY_EXE=""
PY_LABEL=""
TARGET_PY=""
TARGET_LABEL=""

if [ -x "$SCRIPT_DIR/.venv/bin/python" ]; then
    PY_EXE="$SCRIPT_DIR/.venv/bin/python"
    PY_LABEL=".venv/bin/python"
elif [ -x "$SCRIPT_DIR/.venv/bin/python3" ]; then
    PY_EXE="$SCRIPT_DIR/.venv/bin/python3"
    PY_LABEL=".venv/bin/python3"
elif command -v python3 >/dev/null 2>&1; then
    PY_EXE=$(command -v python3)
    PY_LABEL="python3"
elif command -v python >/dev/null 2>&1; then
    PY_EXE=$(command -v python)
    PY_LABEL="python"
else
    echo "[ERROR] Python was not found."
    echo "[ERROR] Create .venv or install python3/python first."
    exit 1
fi

if [ -f "$SCRIPT_DIR/origin.py" ]; then
    TARGET_PY="$SCRIPT_DIR/origin.py"
    TARGET_LABEL="origin.py"
elif [ -f "$SCRIPT_DIR/run_a_py_parallel.py" ] && find "$SCRIPT_DIR" -maxdepth 1 -type f -name 'a*.py' | grep -q .; then
    TARGET_PY="$SCRIPT_DIR/run_a_py_parallel.py"
    TARGET_LABEL="run_a_py_parallel.py"
else
    echo "[ERROR] No runnable entry was found."
    echo "[ERROR] Expected origin.py, or run_a_py_parallel.py with a*.py files."
    exit 1
fi

echo "[INFO] Using Python: $PY_LABEL"
echo "[INFO] Entry: $TARGET_LABEL"

RUN_A_PY_LABEL="$PY_LABEL" exec "$PY_EXE" "$TARGET_PY" "$@"
