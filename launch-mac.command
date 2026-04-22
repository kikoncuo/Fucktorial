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

# If a prior run left a half-built .venv without a marker, wipe it.
if [ -d "$VENV" ] && [ ! -f "$MARKER" ]; then
    warn "Removing incomplete .venv from a previous run…"
    rm -rf "$VENV"
fi

# ── First-time setup ──────────────────────────────────────────────────────
log "First-time setup — this takes a minute."

# Homebrew
if ! command -v brew >/dev/null 2>&1; then
    log "Installing Homebrew (you may be asked for your password)…"
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" \
        || die "Homebrew install failed."
fi
if [ -x /opt/homebrew/bin/brew ]; then eval "$(/opt/homebrew/bin/brew shellenv)"
elif [ -x /usr/local/bin/brew ]; then eval "$(/usr/local/bin/brew shellenv)"
fi

# ── Pick a Python that has Tk AND can build a working venv ───────────────
#
# Some Pythons on PATH look fine but are not venv-friendly:
#   * uv-managed pythons (~/.local/share/uv/python/...) are relocatable and
#     have sys.prefix = "/install", so `python -m venv` fails bootstrapping pip.
#   * pyenv shims can be flaky depending on shim init.
# We therefore enumerate explicit paths first, skip known-bad prefixes, and
# then *validate* each candidate by actually creating a throwaway venv.
try_candidate() {
    local bin="$1"
    [ -x "$bin" ] || return 1
    case "$bin" in
        */uv/*|*/.local/share/uv/*) return 1 ;;
    esac
    "$bin" -c "import tkinter" 2>/dev/null || return 1
    local probe
    probe="$(mktemp -d)/venv"
    if "$bin" -m venv "$probe" >/dev/null 2>&1 \
       && [ -x "$probe/bin/python" ] \
       && "$probe/bin/python" -c "import sys, os; sys.exit(0 if os.path.isfile(sys.executable) else 1)" >/dev/null 2>&1 \
       && "$probe/bin/python" -m pip --version >/dev/null 2>&1; then
        rm -rf "$(dirname "$probe")"
        return 0
    fi
    rm -rf "$(dirname "$probe")" 2>/dev/null || true
    return 1
}

resolve_candidates() {
    local names=(python3.12 python3.11 python3.13 python3.14 python3)
    # Explicit brew + python.org paths first
    for p in /opt/homebrew/bin /usr/local/bin; do
        for n in "${names[@]}"; do
            [ -x "$p/$n" ] && echo "$p/$n"
        done
    done
    # Then anything else on PATH (lower priority)
    for n in "${names[@]}"; do
        # Iterate through all locations of `n` on PATH, not just the first.
        IFS=:
        for dir in $PATH; do
            [ -x "$dir/$n" ] && echo "$dir/$n"
        done
        unset IFS
    done
}

PICK_PY=""
while IFS= read -r cand; do
    # Dedup: skip if we've tried this exact path already
    case "$tried" in *"|$cand|"*) continue ;; esac
    tried="${tried}|$cand|"
    if try_candidate "$cand"; then
        PICK_PY="$cand"
        break
    fi
done < <(resolve_candidates)

if [ -z "$PICK_PY" ]; then
    log "No working Python with Tk found — installing python@3.12 + Tk via Homebrew…"
    brew install python@3.12 python-tk@3.12 || die "brew install python@3.12 failed."
    BREW_PY="$(brew --prefix python@3.12)/bin/python3.12"
    if try_candidate "$BREW_PY"; then
        PICK_PY="$BREW_PY"
    else
        die "Homebrew python@3.12 installed but still can't create a working venv."
    fi
fi

log "Using $PICK_PY ($("$PICK_PY" --version))."

# ── Create venv ──────────────────────────────────────────────────────────
log "Creating virtual environment in $VENV…"
"$PICK_PY" -m venv "$VENV" || die "venv creation failed."

# shellcheck disable=SC1091
source "$VENV/bin/activate"

log "Installing Python dependencies…"
python -m pip install --upgrade pip >/dev/null
python -m pip install -r requirements.txt >/dev/null || die "pip install failed."

python -c "from playwright.sync_api import sync_playwright" 2>/dev/null || die "Playwright didn't install cleanly."

# ── Chromium for Playwright (skip if already installed) ──────────────────
if ! ls "$HOME/Library/Caches/ms-playwright"/chromium-* >/dev/null 2>&1; then
    log "Downloading Chromium for Playwright (one-time, ~150 MB)…"
    python -m playwright install chromium \
        || warn "Chromium install failed — Log In can still work by reading from your regular Chrome."
fi

touch "$MARKER"
log "Setup complete. Launching Fucktorial…"
exec python gui.py
