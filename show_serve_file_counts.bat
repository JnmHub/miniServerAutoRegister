@echo off
setlocal EnableExtensions

pushd "%~dp0" >nul

set "PY_EXE="
set "PY_ARGS="
set "PY_LABEL="
set "TARGET_PY=%~dp0show_serve_file_counts.py"

where py >nul 2>nul
if not errorlevel 1 (
    set "PY_EXE=py"
    set "PY_ARGS=-3"
    set "PY_LABEL=py -3"
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

if not exist "%TARGET_PY%" (
    echo [ERROR] show_serve_file_counts.py was not found: %TARGET_PY%
    popd >nul
    exit /b 1
)

echo [INFO] Using Python: %PY_LABEL%
echo [INFO] Entry: show_serve_file_counts.py
if exist "%~dp0requirements.txt" (
    echo [INFO] Installing requirements.txt with global Python
    "%PY_EXE%" %PY_ARGS% -m pip --version >nul 2>nul
    if errorlevel 1 (
        "%PY_EXE%" %PY_ARGS% -m ensurepip --upgrade >nul 2>nul
    )
    "%PY_EXE%" %PY_ARGS% -m pip install -r "%~dp0requirements.txt"
    if errorlevel 1 (
        set "EXIT_CODE=%ERRORLEVEL%"
        popd >nul
        exit /b %EXIT_CODE%
    )
)

"%PY_EXE%" %PY_ARGS% "%TARGET_PY%" %*
set "EXIT_CODE=%ERRORLEVEL%"
popd >nul
exit /b %EXIT_CODE%
