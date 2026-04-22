@echo off
REM Fucktorial — one-click launcher for Windows.
REM Double-click this file. First run installs everything; later runs launch instantly.
setlocal EnableDelayedExpansion
cd /d "%~dp0"

set "VENV=.venv"
set "MARKER=%VENV%\.fucktorial-ready"

REM -- Fast path -------------------------------------------------------------
if exist "%MARKER%" if exist "%VENV%\Scripts\pythonw.exe" (
    start "" "%VENV%\Scripts\pythonw.exe" gui.py
    exit /b
)

REM -- Clean half-built venv from a previous failed run ---------------------
if exist "%VENV%" (
    if not exist "%MARKER%" (
        echo [!] Removing incomplete .venv from a previous run...
        rmdir /s /q "%VENV%"
    )
)

echo.
echo   Fucktorial  -  one-time setup
echo   =============================
echo.

REM -- Build an ordered list of candidate Python launchers -------------------
set "CANDIDATES=py python3.12 python3.11 python3.13 python python3"

REM -- Probe each candidate: must have tkinter AND be able to create a venv --
set "PICK_PY="
for %%C in (%CANDIDATES%) do (
    if not defined PICK_PY (
        call :try_candidate %%C
    )
)

if not defined PICK_PY (
    echo [+] No working Python found. Installing Python 3.12 via winget...
    where winget >nul 2>nul
    if errorlevel 1 (
        echo [x] winget is not available on this machine.
        echo     Install Python 3.12 manually from https://www.python.org/downloads/
        echo     and re-run this launcher.
        pause
        exit /b 1
    )
    winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
    REM Retry probe after install
    for %%C in (py python3.12 python3 python) do (
        if not defined PICK_PY call :try_candidate %%C
    )
    if not defined PICK_PY (
        echo [x] Python installed but launcher cannot find a working copy on PATH.
        echo     Close this window, open a new one, and re-run the launcher.
        pause
        exit /b 1
    )
)

echo [+] Using: %PICK_PY%
%PICK_PY% --version

echo [+] Creating virtual environment in %VENV%...
%PICK_PY% -m venv %VENV% || (echo [x] venv creation failed. & pause & exit /b 1)

call "%VENV%\Scripts\activate.bat"

echo [+] Installing Python dependencies...
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt >nul || (echo [x] pip failed. & pause & exit /b 1)

python -c "from playwright.sync_api import sync_playwright" 2>nul
if errorlevel 1 (
    echo [x] Playwright did not install cleanly.
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
exit /b

REM -- Subroutine: validate a candidate by actually building a throwaway venv
:try_candidate
set "CAND=%~1"
where %CAND% >nul 2>nul || exit /b
REM Skip uv-managed pythons (not venv-friendly)
for /f "delims=" %%P in ('where %CAND% 2^>nul') do (
    echo %%P | findstr /i "\\uv\\" >nul && exit /b
    echo %%P | findstr /i "\\.local\\" >nul && exit /b
)
%CAND% -c "import tkinter" 2>nul
if errorlevel 1 exit /b
REM Build a throwaway venv under %TEMP% and verify pip works
set "PROBE=%TEMP%\fucktorial_probe_%RANDOM%"
%CAND% -m venv "%PROBE%" >nul 2>nul
if errorlevel 1 (
    rmdir /s /q "%PROBE%" 2>nul
    exit /b
)
"%PROBE%\Scripts\python.exe" -m pip --version >nul 2>nul
if errorlevel 1 (
    rmdir /s /q "%PROBE%" 2>nul
    exit /b
)
rmdir /s /q "%PROBE%" 2>nul
set "PICK_PY=%CAND%"
exit /b
