@echo off
REM Fucktorial — one-click launcher for Windows.
REM Double-click this file. First run installs everything; later runs just launch.
setlocal EnableDelayedExpansion
cd /d "%~dp0"

set "VENV=.venv"
set "MARKER=%VENV%\.fucktorial-ready"

REM -- Fast path -------------------------------------------------------------
if exist "%MARKER%" if exist "%VENV%\Scripts\pythonw.exe" (
    start "" "%VENV%\Scripts\pythonw.exe" gui.py
    exit /b
)

echo.
echo   Fucktorial  —  one-time setup
echo   ============================
echo.

REM -- Locate Python (must be 3.11+) -----------------------------------------
set "PY="
for %%C in (py python3 python) do (
    if not defined PY (
        where %%C >nul 2>nul && set "PY=%%C"
    )
)

if not defined PY (
    echo [+] Python not found. Installing via winget...
    where winget >nul 2>nul
    if errorlevel 1 (
        echo [x] winget is not available on this machine.
        echo     Install Python 3.12 manually from https://www.python.org/downloads/
        echo     and re-run this launcher.
        pause
        exit /b 1
    )
    winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
    set "PY=py"
)

echo [+] Using: %PY%
%PY% --version

if not exist "%VENV%\Scripts\python.exe" (
    echo [+] Creating virtual environment...
    %PY% -m venv %VENV% || (echo [x] venv failed. & pause & exit /b 1)
)

call "%VENV%\Scripts\activate.bat"

echo [+] Installing Python dependencies...
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt >nul || (echo [x] pip failed. & pause & exit /b 1)

python -c "from playwright.sync_api import sync_playwright" 2>nul
if errorlevel 1 (
    echo [x] Playwright didn't install cleanly.
    pause
    exit /b 1
)

REM -- Chromium for Playwright ----------------------------------------------
if not exist "%LOCALAPPDATA%\ms-playwright\chromium-*" (
    echo [+] Downloading Chromium for Playwright ^(one-time, ~150 MB^)...
    python -m playwright install chromium
)

type nul > "%MARKER%"
echo [+] Setup complete. Launching Fucktorial...
start "" pythonw gui.py
endlocal
