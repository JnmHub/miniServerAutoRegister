#!/bin/sh

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$SCRIPT_DIR" || exit 1

PY_EXE=""
PY_LABEL=""

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

RUN_A_PY_LABEL="$PY_LABEL" exec "$PY_EXE" "$SCRIPT_DIR/run_a_py_parallel.py" "$@"
