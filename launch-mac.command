#!/usr/bin/env bash
# Fucktorial launcher for macOS.
# Double-click this file to run the GUI.
# Auto-installs: Homebrew, Python 3.11 + tkinter, and the Python deps.
set -e
cd "$(dirname "$0")"

log()  { printf "\033[1;36m▶ %s\033[0m\n" "$*"; }
warn() { printf "\033[1;33m! %s\033[0m\n" "$*"; }
die()  { printf "\033[1;31m✗ %s\033[0m\n" "$*"; exit 1; }

# ── Homebrew ──────────────────────────────────────────────────────────────
if ! command -v brew >/dev/null 2>&1; then
    log "Homebrew not found — installing (you may be asked for your password)…"
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    # Add brew to PATH for this shell
    if [ -x /opt/homebrew/bin/brew ]; then eval "$(/opt/homebrew/bin/brew shellenv)"
    elif [ -x /usr/local/bin/brew ]; then eval "$(/usr/local/bin/brew shellenv)"
    fi
fi

# ── Pick a Python that has tkinter ───────────────────────────────────────
PICK_PY=""
for candidate in python3.12 python3.11 python3.13 python3.14 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
        if "$candidate" -c "import tkinter" 2>/dev/null; then
            PICK_PY="$candidate"
            break
        fi
    fi
done

if [ -z "$PICK_PY" ]; then
    log "No Python with Tk found — installing python@3.12 and python-tk@3.12 via Homebrew…"
    brew install python@3.12 python-tk@3.12
    PICK_PY="python3.12"
fi

log "Using: $PICK_PY ($("$PICK_PY" --version))"

# ── Virtualenv for deps ───────────────────────────────────────────────────
VENV=".venv"
if [ ! -d "$VENV" ]; then
    log "Creating virtual environment in $VENV…"
    "$PICK_PY" -m venv "$VENV"
fi

# shellcheck disable=SC1091
source "$VENV/bin/activate"

log "Installing Python dependencies (first run only takes ~1 minute)…"
python -m pip install --upgrade pip >/dev/null
python -m pip install -r requirements.txt >/dev/null

if ! python -c "import playwright" 2>/dev/null; then
    die "Playwright failed to install."
fi

# Install chromium if not present
if ! python -m playwright install --dry-run chromium 2>/dev/null | grep -q "is already installed"; then
    log "Installing Chromium for Playwright (one-time, ~150 MB)…"
    python -m playwright install chromium
fi

# ── Launch ────────────────────────────────────────────────────────────────
log "Starting Fucktorial…"
exec python gui.py
