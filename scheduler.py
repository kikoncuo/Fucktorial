"""Timezone-aware scheduling engine for Factorial clock-in automation."""

import logging
import signal
import time as time_module
from datetime import datetime, timedelta, date
from typing import Optional
from zoneinfo import ZoneInfo

from config import (
    get_schedule_for_date,
    SLEEP_INTERVAL_SECONDS,
    GRACE_WINDOW_MINUTES,
    TIMEZONE,
)
from state import (
    load_state,
    init_today,
    mark_action,
    get_overdue_actions,
    get_missed_actions,
    get_pending_actions,
)
from api import FactorialAPI
from audio import notify_action_completed, notify_action_missed
from holidays import is_workday

logger = logging.getLogger("scheduler")

TZ = ZoneInfo(TIMEZONE)
_running = True


def _signal_handler(sig, frame):
    global _running
    logger.info("Received signal %s — shutting down gracefully", sig)
    _running = False


def _now_madrid() -> datetime:
    """Return current datetime in Europe/Madrid timezone."""
    return datetime.now(TZ)


def _today_isodate() -> str:
    return _now_madrid().date().isoformat()


def compute_today_actions() -> list[tuple[str, datetime]]:
    """Return sorted list of (action_name, scheduled_datetime) for today."""
    today = _now_madrid().date()
    schedule = get_schedule_for_date(today)
    result = []
    for action, t in schedule.items():
        scheduled = datetime(today.year, today.month, today.day, t.hour, t.minute, tzinfo=TZ)
        result.append((action, scheduled))
    return result


def _seconds_until(target: datetime) -> float:
    """Seconds from now until target datetime."""
    delta = target - _now_madrid()
    return max(0, delta.total_seconds())


def _handle_missed_actions(state: dict, today: str) -> None:
    """Mark actions past their grace window as missed."""
    now = _now_madrid()
    missed = get_missed_actions(state, today, now)
    for action in missed:
        mark_action(state, today, action, "missed")
        notify_action_missed()
        logger.warning("Action %s was missed (past grace window)", action)


def _handle_overdue_actions(api: FactorialAPI, state: dict, today: str) -> int:
    """Execute actions that are overdue but within grace window.

    Returns the number of actions executed.
    """
    now = _now_madrid()
    overdue = get_overdue_actions(state, today, now)
    executed = 0
    for action in overdue:
        logger.info("Executing overdue action: %s", action)
        success = api.execute_smart_action(action)
        if success:
            mark_action(state, today, action, "completed")
            notify_action_completed()
            executed += 1
        else:
            mark_action(state, today, action, "failed")
    return executed


def run_schedule_mode(api: FactorialAPI) -> None:
    """Main daemon loop — sleep between scheduled actions."""
    global _running
    _running = True

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    logger.info("Starting schedule mode (daemon)")

    while _running:
        today_str = _today_isodate()
        today_date = _now_madrid().date()

        # ── Check workday ──────────────────────────────────────────
        if not is_workday(today_date):
            logger.info("Today (%s) is not a workday — sleeping until tomorrow", today_str)
            _sleep_until_tomorrow()
            continue

        # ── Load & init state ──────────────────────────────────────
        state = load_state()
        state = init_today(state)

        # ── Handle missed & overdue ────────────────────────────────
        _handle_missed_actions(state, today_str)
        _handle_overdue_actions(api, state, today_str)

        # ── Find next pending action ──────────────────────────────
        pending = get_pending_actions(state, today_str)
        if not pending:
            logger.info("All actions completed for today — sleeping until tomorrow")
            _sleep_until_tomorrow()
            continue

        # Get the next scheduled time for a pending action
        next_action = None
        next_time = None
        for action, scheduled in compute_today_actions():
            if action in pending:
                next_action = action
                next_time = scheduled
                break

        if next_action is None or next_time is None:
            logger.info("No more scheduled actions for today")
            _sleep_until_tomorrow()
            continue

        now = _now_madrid()

        # If next action is in the future, sleep until then
        if next_time > now:
            secs = _seconds_until(next_time)
            logger.info(
                "Next action: %s at %s — sleeping %.0fs",
                next_action,
                next_time.strftime("%H:%M"),
                secs,
            )
            _sleep_with_check(secs)

            if not _running:
                break

        # ── Execute the action ─────────────────────────────────────
        logger.info("Executing scheduled action: %s", next_action)

        # Reload state in case it changed during sleep
        state = load_state()
        state = init_today(state)

        # Double-check it's still pending
        if state.get(today_str, {}).get(next_action, {}).get("status") != "pending":
            logger.info("Action %s no longer pending — skipping", next_action)
            continue

        success = api.execute_smart_action(next_action)
        if success:
            mark_action(state, today_str, next_action, "completed")
            notify_action_completed()
        else:
            mark_action(state, today_str, next_action, "failed")

        # Brief pause before next iteration
        time_module.sleep(5)

    logger.info("Schedule mode exited")


def run_now_mode(api: FactorialAPI) -> None:
    """Execute the next pending action immediately, then exit."""
    today_str = _today_isodate()

    if not is_workday(_now_madrid().date()):
        logger.info("Today (%s) is not a workday — no actions to perform", today_str)
        return

    state = load_state()
    state = init_today(state)

    # Handle overdue actions first
    _handle_missed_actions(state, today_str)
    _handle_overdue_actions(api, state, today_str)

    # Find next pending action
    pending = get_pending_actions(state, today_str)
    if not pending:
        logger.info("All actions completed for today")
        return

    next_action = pending[0]
    logger.info("Executing next pending action: %s", next_action)

    success = api.execute_smart_action(next_action)
    if success:
        mark_action(state, today_str, next_action, "completed")
        notify_action_completed()
    else:
        mark_action(state, today_str, next_action, "failed")

    logger.info("Now mode complete")


def run_force_mode(api: FactorialAPI, action: str) -> None:
    """Force-execute a specific action regardless of schedule or state."""
    today_str = _today_isodate()

    state = load_state()
    state = init_today(state)

    logger.info("Force-executing action: %s", action)
    success = api.perform_action(action)
    if success:
        mark_action(state, today_str, action, "completed")
        notify_action_completed()
    else:
        mark_action(state, today_str, action, "failed")


# ── Sleep helpers ───────────────────────────────────────────────────────

def _sleep_until_tomorrow() -> None:
    """Sleep until midnight Europe/Madrid."""
    global _running
    now = _now_madrid()
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=5, second=0, microsecond=0)
    secs = _seconds_until(tomorrow)
    logger.info("Sleeping until tomorrow (~%.0f seconds)", secs)
    _sleep_with_check(secs)


def _sleep_with_check(total_seconds: float) -> None:
    """Sleep in SLEEP_INTERVAL chunks, checking _running flag each cycle."""
    global _running
    remaining = total_seconds
    while remaining > 0 and _running:
        chunk = min(remaining, SLEEP_INTERVAL_SECONDS)
        time_module.sleep(chunk)
        remaining -= chunk
