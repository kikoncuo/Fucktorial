#!/usr/bin/env bash
# Fucktorial — one-click launcher for macOS.
# Double-click this file in Finder. First run installs everything; later runs
# just launch the app.
set -e
cd "$(dirname "$0")"

log()  { printf "\033[1;36m▶\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33m!\033[0m %s\n" "$*"; }
die()  { printf "\033[1;31m✗\033[0m %s\n" "$*"; printf "\nPress any key to close this window…"; read -n 1; exit 1; }

VENV=".venv"
MARKER="$VENV/.fucktorial-ready"

# ── Fast path ─────────────────────────────────────────────────────────────
if [ -f "$MARKER" ] && [ -x "$VENV/bin/python" ]; then
    exec "$VENV/bin/python" gui.py
fi

# ── First-time setup ──────────────────────────────────────────────────────
log "First-time setup — this takes a minute."

# Homebrew
if ! command -v brew >/dev/null 2>&1; then
    log "Installing Homebrew (you may be asked for your password)…"
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" \
        || die "Homebrew install failed."
    if [ -x /opt/homebrew/bin/brew ]; then eval "$(/opt/homebrew/bin/brew shellenv)"
    elif [ -x /usr/local/bin/brew ]; then eval "$(/usr/local/bin/brew shellenv)"
    fi
fi

# Python with tkinter
PICK_PY=""
for candidate in python3.12 python3.11 python3.13 python3.14 python3; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c "import tkinter" 2>/dev/null; then
        PICK_PY="$candidate"; break
    fi
done
if [ -z "$PICK_PY" ]; then
    log "Installing Python 3.12 + Tk via Homebrew…"
    brew install python@3.12 python-tk@3.12 || die "Python install failed."
    PICK_PY="python3.12"
fi
log "Using $PICK_PY ($("$PICK_PY" --version))."

# Virtualenv
if [ ! -d "$VENV" ]; then
    log "Creating virtual environment…"
    "$PICK_PY" -m venv "$VENV" || die "venv creation failed."
fi

# shellcheck disable=SC1091
source "$VENV/bin/activate"

log "Installing Python dependencies…"
python -m pip install --upgrade pip >/dev/null
python -m pip install -r requirements.txt >/dev/null || die "pip install failed."

# Chromium for Playwright (skip if already installed)
if ! python -c "from playwright.sync_api import sync_playwright as _" 2>/dev/null; then
    die "Playwright didn't install cleanly."
fi
if ! ls "$HOME/Library/Caches/ms-playwright"/chromium-* >/dev/null 2>&1; then
    log "Downloading Chromium for Playwright (one-time, ~150 MB)…"
    python -m playwright install chromium || warn "Chromium install failed — Log In may fall back to reading from your regular Chrome only."
fi

touch "$MARKER"
log "Setup complete. Launching Fucktorial…"
exec python gui.py
