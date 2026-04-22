@echo off
REM Fucktorial launcher for Windows.
REM Double-click this file to run the GUI.
REM Auto-installs Python (via winget) and dependencies on first run.
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo.
echo ============================================
echo   Fucktorial launcher
echo ============================================
echo.

REM -- Locate Python (must be 3.11+) -----------------------------------------
set "PY="
for %%C in (py python3 python) do (
    if not defined PY (
        where %%C >nul 2>nul && set "PY=%%C"
    )
)

if not defined PY (
    echo [!] Python not found. Installing via winget...
    where winget >nul 2>nul
    if errorlevel 1 (
        echo [x] winget is not available on this machine.
        echo     Please install Python 3.12 manually from https://www.python.org/downloads/
        echo     and re-run this launcher.
        pause
        exit /b 1
    )
    winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
    REM PATH may not refresh in this session — use py from standard install
    set "PY=py"
)

echo [+] Using: %PY%
%PY% --version

REM -- Virtual environment ---------------------------------------------------
if not exist ".venv\Scripts\python.exe" (
    echo [+] Creating virtual environment...
    %PY% -m venv .venv
)

call ".venv\Scripts\activate.bat"

echo [+] Installing Python dependencies (first run only)...
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt >nul

REM -- Chromium for Playwright ----------------------------------------------
python -m playwright install --dry-run chromium 2>nul | findstr /C:"is already installed" >nul
if errorlevel 1 (
    echo [+] Installing Chromium for Playwright ^(~150 MB, one-time^)...
    python -m playwright install chromium
)

echo [+] Starting Fucktorial...
start "" pythonw gui.py
endlocal
