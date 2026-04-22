#!/usr/bin/env python3
"""Factorial HR Clock-in Automation — Entry Point.

Uses direct GraphQL API calls instead of browser automation.
Cookies are refreshed from the user's Chrome browser via Playwright only when needed.

Usage:
    python main.py                                # Run as daemon (friday-6h mode)
    python main.py --schedule                     # Same as above
    python main.py --schedule-mode standard       # Use 8h30 schedule every weekday
    python main.py --now                          # Execute next pending action immediately
    python main.py --force fichar                 # Force a specific action right now
    python main.py --refresh                      # Refresh cookies from browser, then exit
    python main.py --backfill                     # Backfill past 7 days of missing shifts
    python main.py --backfill 14                  # Backfill past 14 days
"""

import argparse
import logging
import sys
import subprocess

try:
    import fcntl  # POSIX
    _HAS_FCNTL = True
except ImportError:
    import msvcrt  # Windows
    _HAS_FCNTL = False

from config import (
    LOCK_FILE,
    LOG_FILE,
    SCRIPT_DIR,
    DEFAULT_SCHEDULE_MODE,
    SCHEDULE_MODE_FRIDAY_6H,
    SCHEDULE_MODE_STANDARD,
    set_schedule_mode,
)


def setup_logging() -> None:
    """Configure logging to file and console."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # File handler
    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(file_handler)
    root.addHandler(console_handler)


def ensure_dependencies() -> None:
    """Check and install required dependencies."""
    logger = logging.getLogger("main")

    # Check requests
    try:
        import requests  # noqa: F401
    except ImportError:
        logger.info("Installing requests...")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--break-system-packages", "requests"],
            stdout=subprocess.DEVNULL,
        )

    # Check playwright (only needed for cookie refresh)
    try:
        import playwright  # noqa: F401
    except ImportError:
        logger.info("Installing playwright (for cookie refresh)...")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--break-system-packages", "playwright"],
            stdout=subprocess.DEVNULL,
        )
        subprocess.check_call(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            stdout=subprocess.DEVNULL,
        )


def acquire_lock() -> object:
    """Acquire a file lock to prevent multiple instances."""
    logger = logging.getLogger("main")
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    lock_file = open(LOCK_FILE, "w")
    try:
        if _HAS_FCNTL:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        else:
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        logger.info("Lock acquired: %s", LOCK_FILE)
        return lock_file
    except (IOError, OSError):
        logger.error("Another instance is already running. Exiting.")
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Factorial HR Clock-in Automation (API-based)"
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--schedule", action="store_true", default=True,
        help="Run as daemon (default)",
    )
    mode.add_argument(
        "--now", action="store_true",
        help="Execute next pending action immediately",
    )
    mode.add_argument(
        "--force", type=str, metavar="ACTION",
        choices=["fichar", "pausar", "reanudar", "salida"],
        help="Force a specific action regardless of schedule",
    )
    mode.add_argument(
        "--backfill", type=int, nargs="?", const=7, metavar="DAYS",
        help="Backfill past N days of missing shifts (default: 7)",
    )
    mode.add_argument(
        "--backfill-today", action="store_true",
        help="Backfill today's missed slots (only slots whose end-time has passed)",
    )
    mode.add_argument(
        "--refresh", action="store_true",
        help="Refresh cookies from your real Chrome (no browser launch), then exit",
    )
    mode.add_argument(
        "--refresh-browser", action="store_true",
        help="Fallback: refresh cookies from a Playwright Chromium window, then exit",
    )
    parser.add_argument(
        "--schedule-mode",
        choices=[SCHEDULE_MODE_FRIDAY_6H, SCHEDULE_MODE_STANDARD],
        default=DEFAULT_SCHEDULE_MODE,
        help="Schedule template to use: friday-6h (default) or standard",
    )

    args = parser.parse_args()
    set_schedule_mode(args.schedule_mode)

    # ── Setup ────────────────────────────────────────────────────────
    setup_logging()
    logger = logging.getLogger("main")
    logger.info("=" * 60)
    logger.info("Factorial HR Clock-in Automation starting (API mode)")
    mode_str = (
        "refresh (chrome)" if args.refresh
        else "refresh (browser)" if args.refresh_browser
        else f"backfill {args.backfill}d" if args.backfill is not None
        else "backfill-today" if args.backfill_today
        else "now" if args.now
        else "force " + args.force if args.force
        else "schedule"
    )
    logger.info("Mode: %s", mode_str)
    logger.info("Schedule mode: %s", args.schedule_mode)
    logger.info("Script dir: %s", SCRIPT_DIR)
    logger.info("Python: %s", sys.version.split()[0])

    # ── Dependencies ─────────────────────────────────────────────────
    ensure_dependencies()

    # ── Lock ─────────────────────────────────────────────────────────
    lock_file = acquire_lock()

    # ── API client ───────────────────────────────────────────────────
    from api import FactorialAPI
    from scheduler import run_schedule_mode, run_now_mode, run_force_mode

    api = FactorialAPI()

    try:
        if args.refresh:
            logger.info("Loading cookies from your Chrome browser...")
            if api.load_cookies_from_chrome("chrome"):
                logger.info("Cookies loaded and validated from Chrome!")
            else:
                logger.error(
                    "Failed to load valid cookies from Chrome. "
                    "Open https://app.factorialhr.com in Chrome, sign in, and retry. "
                    "Or use --refresh-browser to open a Playwright login window.")
                sys.exit(1)
            return

        if args.refresh_browser:
            logger.info("Refreshing cookies from Playwright browser...")
            if api.refresh_cookies_from_browser():
                logger.info("Cookies refreshed successfully!")
            else:
                logger.error("Failed to refresh cookies")
                sys.exit(1)
            return

        # Ensure we have cookies for API calls
        if not api._ensure_cookies():
            logger.error("No cookies available and browser refresh failed — exiting")
            sys.exit(1)

        # ── Dispatch ─────────────────────────────────────────────
        if args.backfill is not None:
            logger.info("Backfilling past %d days...", args.backfill)
            results = api.backfill_week(days_back=args.backfill)
            for d, ok in sorted(results.items()):
                status = "OK" if ok else "FAILED"
                logger.info("  %s: %s", d, status)
            filled = sum(1 for v in results.values() if v)
            total = len(results)
            logger.info("Result: %d/%d dates filled", filled, total)
        elif args.backfill_today:
            from datetime import date as _date
            today = _date.today().isoformat()
            logger.info("Backfilling today's missed slots (until_now=True)...")
            slots = api.get_today_slot_status()
            for s in slots:
                logger.info("  %-18s %s-%s  %s",
                            s["label"], s["clock_in"], s["clock_out"], s["status"])
            missed = [s for s in slots if s["status"] == "missed"]
            if not missed:
                logger.info("Nothing to backfill — no missed slots yet")
            else:
                ok = api.backfill_date(today, until_now=True)
                logger.info("Backfill today: %s", "OK" if ok else "FAILED")
        elif args.force:
            run_force_mode(api, args.force)
        elif args.now:
            run_now_mode(api)
        else:
            run_schedule_mode(api)

    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception:
        logger.exception("Unexpected error")
    finally:
        try:
            lock_file.close()
        except Exception:
            pass
        logger.info("Factorial automation shut down")


if __name__ == "__main__":
    main()
