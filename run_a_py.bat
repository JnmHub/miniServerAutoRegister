@echo off
setlocal EnableExtensions

pushd "%~dp0" >nul

set "PY_EXE="
set "PY_ARGS="
set "PY_LABEL="

if exist ".venv\Scripts\python.exe" (
    set "PY_EXE=%cd%\.venv\Scripts\python.exe"
    set "PY_LABEL=.venv\Scripts\python.exe"
)

if not defined PY_EXE if exist ".venv\Scripts\python.bat" (
    set "PY_EXE=%cd%\.venv\Scripts\python.bat"
    set "PY_LABEL=.venv\Scripts\python.bat"
)

if not defined PY_EXE if exist ".venv\bin\python.exe" (
    set "PY_EXE=%cd%\.venv\bin\python.exe"
    set "PY_LABEL=.venv\bin\python.exe"
)

if not defined PY_EXE if exist ".venv\bin\python" (
    set "PY_EXE=%cd%\.venv\bin\python"
    set "PY_LABEL=.venv\bin\python"
)

if not defined PY_EXE (
    where py >nul 2>nul
    if not errorlevel 1 (
        set "PY_EXE=py"
        set "PY_ARGS=-3"
        set "PY_LABEL=py -3"
    )
)

if not defined PY_EXE (
    where python >nul 2>nul
    if not errorlevel 1 (
        set "PY_EXE=python"
        set "PY_LABEL=python"
    )
)

if not defined PY_EXE (
    echo [ERROR] Python was not found in PATH.
    echo [ERROR] Install Python or add "py"/"python" to PATH first.
    popd >nul
    exit /b 1
)

set "RUN_A_PY_LABEL=%PY_LABEL%"
"%PY_EXE%" %PY_ARGS% "%~dp0run_a_py_parallel.py" %*
set "EXIT_CODE=%ERRORLEVEL%"
popd >nul
exit /b %EXIT_CODE%
