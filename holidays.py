"""Spanish and Valencia regional holiday detection."""

import json
import logging
from datetime import date
from pathlib import Path

from config import LOCAL_HOLIDAYS_FILE

logger = logging.getLogger("holidays")

# ── National Spanish holidays (fixed date) ─────────────────────────────────
# Format: (month, day, name)
_NATIONAL_FIXED: list[tuple[int, int, str]] = [
    (1,  1,  "Año Nuevo"),
    (1,  6,  "Reyes Magos"),
    (5,  1,  "Día del Trabajador"),
    (8, 15,  "Asunción de la Virgen"),
    (10, 12, "Fiesta Nacional de España"),
    (11,  1, "Todos los Santos"),
    (12,  6, "Día de la Constitución"),
    (12,  8,  "Inmaculada Concepción"),
    (12, 25, "Navidad"),
]

# ── Valencia regional holidays (fixed date) ────────────────────────────────
_REGIONAL_FIXED: list[tuple[int, int, str]] = [
    (3, 19, "San José"),           # Only Valencia
    (10, 9, "Día de la Comunidad Valenciana"),
]

# ── Variable-date holidays (computed per year) ─────────────────────────────

def _easter_sunday(year: int) -> date:
    """Compute Easter Sunday using the Anonymous Gregorian algorithm."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _variable_holidays(year: int) -> list[date]:
    """Compute variable-date holidays for a given year."""
    easter = _easter_sunday(year)
    from datetime import timedelta
    return [
        easter + timedelta(days=-2),   # Viernes Santo (Good Friday)
        easter + timedelta(days=-3),   # Jueves Santo (Maundy Thursday) — Valencia
        # Bon Divendres is the same as Viernes Santo
    ]


def _compute_holidays(year: int) -> set[date]:
    """Compute all holidays for a given year (national + regional + variable)."""
    holidays: set[date] = set()

    for month, day, _ in _NATIONAL_FIXED:
        try:
            holidays.add(date(year, month, day))
        except ValueError:
            pass  # skip invalid dates

    for month, day, _ in _REGIONAL_FIXED:
        try:
            holidays.add(date(year, month, day))
        except ValueError:
            pass

    holidays.update(_variable_holidays(year))
    return holidays


# ── Cache: year → set of dates ─────────────────────────────────────────────
_cache: dict[int, set[date]] = {}


def _get_holidays(year: int) -> set[date]:
    if year not in _cache:
        _cache[year] = _compute_holidays(year)
    return _cache[year]


def _load_local_holidays() -> set[date]:
    """Load user-defined local holidays from local_holidays.json."""
    if not LOCAL_HOLIDAYS_FILE.exists():
        return set()

    holidays: set[date] = set()
    try:
        data = json.loads(LOCAL_HOLIDAYS_FILE.read_text())
        for year_str, date_list in data.items():
            for d in date_list:
                holidays.add(date.fromisoformat(d))
    except Exception as e:
        logger.warning("Failed to load local_holidays.json: %s", e)

    return holidays


def is_holiday(d: date) -> bool:
    """Check if a date is a holiday (national, regional, or local)."""
    if d in _get_holidays(d.year):
        return True
    if d in _load_local_holidays():
        return True
    return False


def is_workday(d: date) -> bool:
    """Return True if the date is a weekday and not a holiday."""
    return d.weekday() < 5 and not is_holiday(d)
