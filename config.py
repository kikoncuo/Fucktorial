"""Central configuration for Factorial HR clock-in automation."""

from collections import OrderedDict
from datetime import date, time
from pathlib import Path

# ── Factorial API ───────────────────────────────────────────────────────────
GRAPHQL_URL = "https://api.factorialhr.com/graphql"
FACTORIAL_APP_URL = "https://app.factorialhr.com/dashboard"
LOGIN_URL_PATTERN = "/users/sign_in"
COMPANY_SELECTOR_URL_PATTERN = "/authentication/company_selector"
COMPANY_NAME = "Laberit Sistemas S.L."

# ── Required Factorial cookies (names only — values come from browser) ──────
FACTORIAL_COOKIE_NAMES = [
    "_factorial_session_v2",
    "cf_clearance",
    "_factorial_id",
    "_factorial_data",
]

# ── Required headers for API calls ─────────────────────────────────────────
REQUIRED_HEADERS = {
    "content-type": "application/json",
    "x-factorial-origin": "web",
    "x-factorial-bigint-support": "true",
    "referer": "https://app.factorialhr.com/",
    "origin": "https://app.factorialhr.com",
}

# ── Break configuration ID (captured from live session) ─────────────────────
BREAK_CONFIGURATION_ID = "27301"

# ── Timezone ────────────────────────────────────────────────────────────────
TIMEZONE = "Europe/Madrid"

# ── Daily schedule (action_name → scheduled time) ──────────────────────────
DEFAULT_SCHEDULE: OrderedDict[str, time] = OrderedDict([
    ("fichar",   time(9,  0)),
    ("pausar",   time(14, 0)),
    ("reanudar", time(14, 30)),
    ("salida",   time(18, 0)),
])

SCHEDULE_MODE_FRIDAY_6H = "friday-6h"
SCHEDULE_MODE_STANDARD = "standard"
DEFAULT_SCHEDULE_MODE = SCHEDULE_MODE_FRIDAY_6H
CURRENT_SCHEDULE_MODE = DEFAULT_SCHEDULE_MODE

FRIDAY_SCHEDULE_6H: OrderedDict[str, time] = OrderedDict([
    ("fichar", time(9, 0)),
    ("salida", time(15, 0)),
])

STANDARD_SHIFT_SLOTS = [
    ("trabajo-mañana", "09:00", "14:00", False),
    ("pausa",          "14:00", "14:30", True),
    ("trabajo-tarde",  "14:30", "18:00", False),
]

FRIDAY_SHIFT_SLOTS_6H = [
    ("trabajo", "09:00", "15:00", False),
]


def set_schedule_mode(mode: str) -> None:
    """Set the active schedule mode for this process."""
    global CURRENT_SCHEDULE_MODE
    CURRENT_SCHEDULE_MODE = mode


def get_schedule_for_date(target_date: date) -> OrderedDict[str, time]:
    """Return the configured schedule for the given date."""
    if CURRENT_SCHEDULE_MODE == SCHEDULE_MODE_FRIDAY_6H and target_date.weekday() == 4:
        return FRIDAY_SCHEDULE_6H
    return DEFAULT_SCHEDULE


def get_shift_slots_for_date(target_date: date) -> list[tuple[str, str, str, bool]]:
    """Return the expected shift slots for the given date."""
    if CURRENT_SCHEDULE_MODE == SCHEDULE_MODE_FRIDAY_6H and target_date.weekday() == 4:
        return FRIDAY_SHIFT_SLOTS_6H
    return STANDARD_SHIFT_SLOTS


def get_expected_work_minutes_for_date(target_date: date) -> int:
    """Return expected worked minutes for the given date."""
    slots = get_shift_slots_for_date(target_date)
    total_minutes = 0
    for _, clock_in, clock_out, is_break in slots:
        if is_break:
            continue
        start_hour, start_minute = map(int, clock_in.split(":"))
        end_hour, end_minute = map(int, clock_out.split(":"))
        total_minutes += (end_hour * 60 + end_minute) - (start_hour * 60 + start_minute)
    return total_minutes

# ── Grace window & sleep ───────────────────────────────────────────────────
GRACE_WINDOW_MINUTES = 30
SLEEP_INTERVAL_SECONDS = 30

# ── Timeouts ────────────────────────────────────────────────────────────────
API_TIMEOUT = 15  # seconds for HTTP requests
ACTION_RETRY_DELAY = 10  # seconds between retries
COOKIES_STALE_AFTER_HOURS = 12  # re-read cookies from browser after this

# ── File paths ─────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent.resolve()


def _user_data_dir() -> Path:
    """Writable per-user directory for Fucktorial state.

    Frozen bundles (PyInstaller .app / .exe) can't write inside the bundle —
    macOS App Translocation makes it read-only — so we use the platform's
    standard per-user data location. Source runs keep using the project
    folder so existing files aren't orphaned on upgrade.
    """
    import os
    import sys
    if not getattr(sys, "frozen", False):
        return SCRIPT_DIR
    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "Fucktorial"
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(home / "AppData" / "Local")
        return Path(base) / "Fucktorial"
    # Linux / BSD / other
    base = os.environ.get("XDG_DATA_HOME") or str(home / ".local" / "share")
    return Path(base) / "Fucktorial"


DATA_DIR = _user_data_dir()
DATA_DIR.mkdir(parents=True, exist_ok=True)

STATE_FILE          = DATA_DIR / "clock_state.json"
LOG_FILE            = DATA_DIR / "factorial.log"
LOCK_FILE           = DATA_DIR / "factorial.lock"
BROWSER_DATA_DIR    = DATA_DIR / "browser_data"
COOKIES_FILE        = DATA_DIR / "factorial_cookies.json"
LOCAL_HOLIDAYS_FILE = DATA_DIR / "local_holidays.json"

# ── macOS system sounds ────────────────────────────────────────────────────
SOUND_LOGIN_NEEDED = "/System/Library/Sounds/Sosumi.aiff"
SOUND_ACTION_COMPLETED = "/System/Library/Sounds/Glass.aiff"
SOUND_ACTION_MISSED = "/System/Library/Sounds/Basso.aiff"
SOUND_ACTION_FAILED = "/System/Library/Sounds/Funk.aiff"
