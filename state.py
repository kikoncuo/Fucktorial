"""JSON state file management for tracking daily clock-in actions."""

import json
import logging
import os
import tempfile
from datetime import date, time, datetime
from pathlib import Path
from typing import Optional

from config import STATE_FILE, GRACE_WINDOW_MINUTES, get_schedule_for_date

logger = logging.getLogger("state")


def load_state() -> dict:
    """Read and parse the state file. Return empty dict if not found."""
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.error("Failed to read state file: %s", e)
        return {}


def save_state(state: dict) -> None:
    """Atomic write: write to temp file then rename."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd, tmp_path = tempfile.mkstemp(
            dir=str(STATE_FILE.parent), suffix=".tmp"
        )
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, str(STATE_FILE))
    except OSError as e:
        logger.error("Failed to save state file: %s", e)


def _today_key() -> str:
    """Return today's date as ISO string (e.g. '2026-04-22')."""
    return date.today().isoformat()


def _ensure_day_entry(state: dict, day: str) -> dict:
    """Create or refresh a day's entry using the active schedule mode."""
    schedule = get_schedule_for_date(date.fromisoformat(day))
    existing = state.get(day, {})
    day_state = {}
    for action, scheduled_time in schedule.items():
        prev = existing.get(action, {})
        day_state[action] = {
            "scheduled": scheduled_time.strftime("%H:%M"),
            "status": prev.get("status", "pending"),
            "executed_at": prev.get("executed_at"),
        }
    state[day] = day_state
    save_state(state)
    return state


def init_today(state: dict) -> dict:
    """Create today's entry with all actions as 'pending' if not present."""
    today = _today_key()
    state = _ensure_day_entry(state, today)
    logger.info("Initialized state for %s", today)
    return state


def mark_action(
    state: dict,
    today: str,
    action: str,
    status: str,
    executed_at: Optional[str] = None,
) -> None:
    """Update an action's status and optionally its execution time."""
    if today not in state:
        state = init_today(state)

    if action not in state[today]:
        logger.warning("Action %s not found in state for %s", action, today)
        return

    state[today][action]["status"] = status
    if executed_at:
        state[today][action]["executed_at"] = executed_at
    elif status == "completed":
        from datetime import datetime as dt
        state[today][action]["executed_at"] = dt.now().strftime("%H:%M:%S")

    save_state(state)
    logger.info("Marked %s/%s as %s", today, action, status)


def get_pending_actions(state: dict, today: str) -> list[str]:
    """Return list of action names with status 'pending'."""
    schedule = get_schedule_for_date(date.fromisoformat(today))
    if today not in state:
        return list(schedule.keys())
    return [
        a for a in schedule.keys()
        if state[today].get(a, {}).get("status") == "pending"
    ]


def _action_datetime(action: str, today_str: str) -> Optional[datetime]:
    """Compute the scheduled datetime for an action on a given date."""
    d = date.fromisoformat(today_str)
    schedule = get_schedule_for_date(d)
    if action not in schedule:
        return None
    t = schedule[action]
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("Europe/Madrid")
    return datetime(d.year, d.month, d.day, t.hour, t.minute, tzinfo=tz)


def get_overdue_actions(state: dict, today: str, now: datetime) -> list[str]:
    """Actions that are pending, past scheduled time, but within grace window."""
    from datetime import timedelta
    overdue = []
    for action in get_pending_actions(state, today):
        scheduled = _action_datetime(action, today)
        if scheduled and scheduled <= now <= scheduled + timedelta(minutes=GRACE_WINDOW_MINUTES):
            overdue.append(action)
    return overdue


def get_missed_actions(state: dict, today: str, now: datetime) -> list[str]:
    """Actions that are pending and past the grace window."""
    from datetime import timedelta
    missed = []
    for action in get_pending_actions(state, today):
        scheduled = _action_datetime(action, today)
        if scheduled and now > scheduled + timedelta(minutes=GRACE_WINDOW_MINUTES):
            missed.append(action)
    return missed
