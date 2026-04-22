"""Factorial HR API client — uses GraphQL directly instead of browser automation.

Cookies are read from the Playwright daemon's browser profile (where the user
is already logged in). If cookies are expired, a new tab is opened in the
existing browser session to refresh them.
"""

import json
import logging
import subprocess
import time as time_module
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import requests

from config import (
    GRAPHQL_URL,
    FACTORIAL_APP_URL,
    REQUIRED_HEADERS,
    BREAK_CONFIGURATION_ID,
    COOKIES_FILE,
    API_TIMEOUT,
    ACTION_RETRY_DELAY,
    TIMEZONE,
    get_shift_slots_for_date,
    get_expected_work_minutes_for_date,
)
from audio import notify_action_failed, notify_login_needed

logger = logging.getLogger("api")

TZ = ZoneInfo(TIMEZONE)


# ── GraphQL mutations (captured from live Factorial HR session) ─────────────

CLOCK_IN_MUTATION = """
mutation ClockIn($locationType: AttendanceShiftLocationTypeEnum, $now: ISO8601DateTime!, $projectTaskId: ID, $projectWorkerId: ID, $source: AttendanceEnumsShiftSourceEnum, $subprojectId: ID, $timeSettingsBreakConfigurationId: ID) {
  attendanceMutations {
    clockInAttendanceShift(
      locationType: $locationType
      now: $now
      projectTaskId: $projectTaskId
      projectWorkerId: $projectWorkerId
      source: $source
      subprojectId: $subprojectId
      timeSettingsBreakConfigurationId: $timeSettingsBreakConfigurationId
    ) {
      errors {
        ... on SimpleError { message type __typename }
        ... on StructuredError { field messages __typename }
        __typename
      }
      shift {
        employee { id openShift { id clockIn clockOut date employeeId locationType workable timeSettingsBreakConfiguration { id name paid __typename } __typename } __typename }
        id automaticClockIn automaticClockOut clockIn clockInWithSeconds clockOut crossesMidnight date employeeId halfDay isOvernight locationType minutes observations periodId referenceDate showPlusOneDay timeSettingsBreakConfiguration { id paid __typename } workable workplace { id name __typename } __typename
      }
      __typename
    }
    __typename
  }
}
"""

CLOCK_OUT_MUTATION = """
mutation ClockOut($endOn: ISO8601Date!, $now: ISO8601DateTime!, $source: AttendanceEnumsShiftSourceEnum, $startOn: ISO8601Date!) {
  attendanceMutations {
    clockOutAttendanceShift(now: $now, source: $source) {
      errors {
        ... on SimpleError { message type __typename }
        ... on StructuredError { field messages __typename }
        __typename
      }
      shift {
        employee { id attendanceShiftsConnection(endOn: $endOn, startOn: $startOn) { nodes { id clockIn clockOut date __typename } __typename } openShift { id clockIn clockOut date employeeId locationType workable __typename } __typename }
        id automaticClockIn automaticClockOut clockIn clockInWithSeconds clockOut crossesMidnight date employeeId halfDay isOvernight locationType minutes observations periodId referenceDate showPlusOneDay __typename
      }
      __typename
    }
    __typename
  }
}
"""

BREAK_START_MUTATION = """
mutation BreakStart($endOn: ISO8601Date!, $now: ISO8601DateTime!, $source: AttendanceEnumsShiftSourceEnum, $startOn: ISO8601Date!, $timeSettingsBreakConfigurationId: ID) {
  attendanceMutations {
    breakStartAttendanceShift(
      now: $now
      source: $source
      systemCreated: false
      timeSettingsBreakConfigurationId: $timeSettingsBreakConfigurationId
    ) {
      errors {
        ... on SimpleError { message type __typename }
        ... on StructuredError { field messages __typename }
        __typename
      }
      shift {
        employee { id attendanceShiftsConnection(endOn: $endOn, startOn: $startOn) { nodes { id clockIn clockOut date __typename } __typename } openShift { id clockIn clockOut date employeeId locationType workable timeSettingsBreakConfiguration { id name paid __typename } __typename } __typename }
        id automaticClockIn automaticClockOut clockIn clockInWithSeconds clockOut crossesMidnight date employeeId halfDay isOvernight locationType minutes observations periodId referenceDate showPlusOneDay __typename
      }
      __typename
    }
    __typename
  }
}
"""

BREAK_END_MUTATION = """
mutation BreakEnd($endOn: ISO8601Date!, $now: ISO8601DateTime!, $source: AttendanceEnumsShiftSourceEnum, $startOn: ISO8601Date!, $systemCreated: Boolean!) {
  attendanceMutations {
    breakEndAttendanceShift(
      now: $now
      source: $source
      systemCreated: $systemCreated
    ) {
      errors {
        ... on SimpleError { message type __typename }
        ... on StructuredError { field messages __typename }
        __typename
      }
      shift {
        employee { id attendanceShiftsConnection(endOn: $endOn, startOn: $startOn) { nodes { id clockIn clockOut date __typename } __typename } openShift { id clockIn clockOut date employeeId locationType workable __typename } __typename }
        id automaticClockIn automaticClockOut clockIn clockInWithSeconds clockOut crossesMidnight date employeeId halfDay isOvernight locationType minutes observations periodId referenceDate showPlusOneDay __typename
      }
      __typename
    }
    __typename
  }
}
"""

OPEN_SHIFT_QUERY = """
query OpenShifts {
  attendance {
    openShiftsConnection {
      nodes {
        id clockIn clockOut date employeeId locationType workable
        timeSettingsBreakConfiguration { id name paid }
      }
    }
  }
}
"""


class FactorialAPI:
    """Lightweight API client for Factorial HR clock-in."""

    def __init__(self) -> None:
        self._session = requests.Session()
        self._cookies: dict[str, str] = {}
        self._load_cookies()

    # ── Cookie management ──────────────────────────────────────────────

    def _load_cookies(self) -> bool:
        """Load cookies from file. Returns True if cookies exist."""
        if not COOKIES_FILE.exists():
            logger.info("No cookies file found")
            return False

        try:
            data = json.loads(COOKIES_FILE.read_text())
            self._cookies = data.get("cookies", {})
            saved_at = data.get("saved_at", "")
            logger.info("Loaded cookies (saved at %s)", saved_at)
            return bool(self._cookies)
        except Exception as e:
            logger.error("Failed to load cookies: %s", e)
            return False

    def _save_cookies(self) -> None:
        """Save current cookies to file."""
        COOKIES_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "cookies": self._cookies,
            "saved_at": datetime.now(TZ).isoformat(),
        }
        COOKIES_FILE.write_text(json.dumps(data, indent=2))
        logger.info("Cookies saved to %s", COOKIES_FILE)

    def refresh_cookies_from_browser(self) -> bool:
        """Refresh cookies by opening a tab in the Playwright browser.

        Uses playwright-cli to open a new tab in the existing browser session
        (which is already logged in), extract fresh cookies via storageState,
        then close the tab.
        """
        logger.info("Refreshing cookies from browser session...")

        # ── Method 1: Use playwright-cli (fastest, reuses existing login) ──
        try:
            session_name = "factorial"
            logger.info("Using playwright-cli session '%s'", session_name)

            # Open a new page in the existing browser
            result = subprocess.run(
                ["playwright-cli", f"-s={session_name}", "open",
                 FACTORIAL_APP_URL, "--persistent", "--headed"],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                logger.warning("playwright-cli open failed: %s", result.stderr[:200])

            time_module.sleep(3)

            # Save storage state (cookies + localStorage)
            state_path = COOKIES_FILE.parent / "_state_tmp.json"
            result = subprocess.run(
                ["playwright-cli", f"-s={session_name}", "state-save",
                 str(state_path)],
                capture_output=True, text=True, timeout=15,
            )

            if result.returncode == 0 and state_path.exists():
                state = json.loads(state_path.read_text())
                cookies = {}
                for cookie in state.get("cookies", []):
                    domain = cookie.get("domain", "")
                    if "factorialhr" in domain:
                        cookies[cookie["name"]] = cookie["value"]

                # Also extract from localStorage (JWT tokens, etc.)
                origins = state.get("origins", [])
                for origin in origins:
                    if "factorialhr" in origin.get("origin", ""):
                        for item in origin.get("localStorage", []):
                            cookies[item["name"]] = item["value"]

                state_path.unlink(missing_ok=True)

                if cookies:
                    self._cookies = cookies
                    self._save_cookies()
                    key_names = [n for n in ["_factorial_session_v2", "cf_clearance"] if n in cookies]
                    logger.info("Extracted %d cookies via playwright-cli (keys: %s)", len(cookies), key_names)
                    return True

            state_path.unlink(missing_ok=True)
            logger.warning("playwright-cli extraction failed")

        except FileNotFoundError:
            logger.info("playwright-cli not found — falling back to Playwright Python")
        except Exception as e:
            logger.warning("playwright-cli method failed: %s", e)

        # ── Method 2: Launch Playwright persistent context ─────────────
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.error("Playwright not installed — cannot refresh cookies")
            return False

        from config import BROWSER_DATA_DIR
        BROWSER_DATA_DIR.mkdir(parents=True, exist_ok=True)

        pw = None
        try:
            pw = sync_playwright().start()
            context = pw.chromium.launch_persistent_context(
                user_data_dir=str(BROWSER_DATA_DIR),
                headless=False,
                locale="es-ES",
                viewport={"width": 1280, "height": 800},
                timezone_id="Europe/Madrid",
            )
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(FACTORIAL_APP_URL, wait_until="domcontentloaded")
            time_module.sleep(5)

            # Check if we need to log in
            if "/sign_in" in page.url:
                logger.warning("Login required — playing alert sound")
                notify_login_needed()
                for _ in range(60):  # wait up to 5 min
                    time_module.sleep(5)
                    if "/sign_in" not in page.url:
                        break
                else:
                    logger.error("Login timeout")
                    return False

            # Handle company selector
            if "/company_selector" in page.url:
                try:
                    from config import COMPANY_NAME
                    btn = page.get_by_role("button", name=COMPANY_NAME)
                    btn.wait_for(state="visible", timeout=10000)
                    btn.click()
                    time_module.sleep(2)
                except Exception as e:
                    logger.error("Failed to select company: %s", e)
                    return False

            time_module.sleep(3)

            # Extract cookies
            all_cookies = context.cookies()
            self._cookies = {}
            for cookie in all_cookies:
                domain = cookie["domain"]
                if "factorialhr" in domain:
                    self._cookies[cookie["name"]] = cookie["value"]

            # Also extract via document.cookie
            try:
                doc_cookies = page.evaluate("() => document.cookie")
                if doc_cookies:
                    for pair in doc_cookies.split(";"):
                        pair = pair.strip()
                        if "=" in pair:
                            name, value = pair.split("=", 1)
                            self._cookies[name.strip()] = value.strip()
            except Exception:
                pass

            key_names = [n for n in ["_factorial_session_v2", "cf_clearance"] if n in self._cookies]
            logger.info("Key cookies found: %s", key_names)

            if not self._cookies:
                logger.error("No Factorial cookies found")
                return False

            self._save_cookies()
            logger.info("Extracted %d cookies via Playwright persistent context", len(self._cookies))
            return True

        except Exception as e:
            logger.error("Playwright persistent context failed: %s", e)
            return False
        finally:
            try:
                if pw:
                    pw.stop()
            except Exception:
                pass

    def _ensure_cookies(self, max_retries: int = 5, retry_interval: int = 60) -> bool:
        """Make sure we have cookies, retrying with alerts if refresh fails.

        Args:
            max_retries: How many times to retry cookie refresh (default 5)
            retry_interval: Seconds between retries (default 60)

        Returns True if cookies are available.
        """
        if self._cookies:
            return True

        logger.warning("No cookies available — need to refresh from browser")
        notify_login_needed()

        for attempt in range(1, max_retries + 1):
            logger.info("Cookie refresh attempt %d/%d...", attempt, max_retries)
            if self.refresh_cookies_from_browser():
                return True

            if attempt < max_retries:
                logger.warning(
                    "Cookie refresh failed — retrying in %ds. "
                    "Make sure you're logged into Factorial in the browser.",
                    retry_interval,
                )
                # Play alert every other attempt
                if attempt % 2 == 1:
                    notify_login_needed()
                time_module.sleep(retry_interval)

        logger.error(
            "Could not get cookies after %d attempts. "
            "Please log into Factorial in your browser and run: python main.py --refresh",
            max_retries,
        )
        return False

    # ── GraphQL request ────────────────────────────────────────────────

    def _graphql_request(
        self,
        operation_name: str,
        query: str,
        variables: dict,
    ) -> Optional[dict]:
        """Send a GraphQL request to the Factorial API."""
        if not self._ensure_cookies():
            logger.error("No cookies — cannot make API request")
            return None

        headers = {
            **REQUIRED_HEADERS,
            "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
        }

        payload = {
            "operationName": operation_name,
            "variables": variables,
            "query": query,
        }

        try:
            resp = self._session.post(
                GRAPHQL_URL,
                params=[("operationName", operation_name)],
                json=payload,
                headers=headers,
                cookies=self._cookies,
                timeout=API_TIMEOUT,
            )

            if resp.status_code in (401, 403):
                logger.warning("Auth error (%d) — cookies are stale, refreshing", resp.status_code)
                # Clear stale cookies and do a full refresh with retries
                self._cookies = {}
                if self._ensure_cookies():
                    resp = self._session.post(
                        GRAPHQL_URL,
                        params=[("operationName", operation_name)],
                        json=payload,
                        headers=headers,
                        cookies=self._cookies,
                        timeout=API_TIMEOUT,
                    )

            resp.raise_for_status()
            data = resp.json()

            # Check for GraphQL errors
            if "errors" in data:
                errors = data["errors"]
                logger.error("GraphQL errors: %s", json.dumps(errors, indent=2)[:500])
                return None

            # Check for mutation-level errors
            try:
                mutations = data["data"]["attendanceMutations"]
                for key in mutations:
                    if isinstance(mutations[key], dict) and mutations[key].get("errors"):
                        errs = mutations[key]["errors"]
                        err_msgs = []
                        for err in errs:
                            if isinstance(err, dict):
                                err_msgs.extend(err.get("messages", []) or [err.get("message", "")])
                            else:
                                err_msgs.append(str(err))
                        err_text = " ".join(err_msgs)

                        # Known "already in expected state" errors — treat as success
                        already_patterns = [
                            "Ya existe un turno en curso",       # Already clocked in
                            "Imposible empezar fichaje",          # Can't clock in (already in)
                            "No hay turno en curso",              # No shift in progress
                            "Imposible fichar la salida",         # Can't clock out
                            "se solapa con el turno",             # Overlapping shift (already exists)
                        ]
                        if any(p in err_text for p in already_patterns):
                            logger.info("Already in expected state: %s", err_text[:100])
                            return data  # Return success — already done

                        logger.error("Mutation errors: %s", json.dumps(errs, indent=2)[:500])
                        return None
            except (KeyError, TypeError):
                pass

            return data

        except requests.exceptions.RequestException as e:
            logger.error("API request failed: %s", e)
            return None

    # ── Action methods ─────────────────────────────────────────────────

    def _now_iso(self) -> str:
        return datetime.now(TZ).isoformat()

    def _today_iso(self) -> str:
        return datetime.now(TZ).date().isoformat()

    def load_cookies_from_chrome(self, browser: str = "chrome") -> bool:
        """Pull Factorial cookies directly from the user's real Chrome browser.

        Uses pycookiecheat to read & decrypt Chrome's cookie store (Keychain on
        macOS, DPAPI on Windows). No Cloudflare challenge because no page load.

        Args:
            browser: 'chrome', 'chromium', 'brave', 'edge', 'opera', 'slack', 'arc'

        Returns True if cookies were extracted and validated via test_cookies().
        """
        try:
            from pycookiecheat import chrome_cookies, BrowserType
        except ImportError:
            logger.error("pycookiecheat not installed — run: pip install pycookiecheat")
            return False

        browser_map = {
            "chrome":   BrowserType.CHROME,
            "chromium": BrowserType.CHROMIUM,
            "brave":    BrowserType.BRAVE,
            "slack":    BrowserType.SLACK,
        }
        bt = browser_map.get(browser.lower(), BrowserType.CHROME)

        extracted: dict[str, str] = {}
        # Factorial sets cookies under both api.factorialhr.com and app.factorialhr.com
        for url in ("https://app.factorialhr.com",
                    "https://api.factorialhr.com"):
            try:
                cookies = chrome_cookies(url, browser=bt)
            except Exception as e:
                logger.warning("Failed to read %s cookies from %s: %s", browser, url, e)
                continue
            if cookies:
                extracted.update(cookies)

        if not extracted:
            logger.warning("No Factorial cookies found in %s — "
                           "are you logged in at https://app.factorialhr.com?", browser)
            return False

        # Stash previous cookies so we can roll back if invalid
        previous = dict(self._cookies)
        self._cookies = extracted

        if not self.test_cookies():
            logger.warning("Cookies extracted from %s but they don't validate — "
                           "log in at https://app.factorialhr.com in %s and try again",
                           browser, browser)
            self._cookies = previous
            return False

        self._save_cookies()
        key_names = [n for n in ["_factorial_session_v2", "cf_clearance"] if n in extracted]
        logger.info("Loaded %d cookies from %s (key cookies: %s)",
                    len(extracted), browser, key_names)
        return True

    def open_login_browser(self):
        """Open a headed Chromium against the persistent profile and return (pw, context).

        The GUI keeps the handles alive while the user logs in, then calls
        capture_cookies_from_login(pw, context) to extract cookies and close.
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.error("Playwright not installed — cannot open login browser")
            return None, None

        from config import BROWSER_DATA_DIR
        BROWSER_DATA_DIR.mkdir(parents=True, exist_ok=True)

        pw = sync_playwright().start()
        context = pw.chromium.launch_persistent_context(
            user_data_dir=str(BROWSER_DATA_DIR),
            headless=False,
            locale="es-ES",
            viewport={"width": 1280, "height": 800},
            timezone_id="Europe/Madrid",
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(FACTORIAL_APP_URL, wait_until="domcontentloaded")
        return pw, context

    def capture_cookies_from_login(self, pw, context) -> bool:
        """Pull cookies from a browser session opened by open_login_browser, then close it."""
        if pw is None or context is None:
            return False
        try:
            all_cookies = context.cookies()
            self._cookies = {}
            for cookie in all_cookies:
                if "factorialhr" in cookie.get("domain", ""):
                    self._cookies[cookie["name"]] = cookie["value"]
            try:
                page = context.pages[0] if context.pages else context.new_page()
                doc_cookies = page.evaluate("() => document.cookie")
                if doc_cookies:
                    for pair in doc_cookies.split(";"):
                        pair = pair.strip()
                        if "=" in pair:
                            name, value = pair.split("=", 1)
                            self._cookies[name.strip()] = value.strip()
            except Exception:
                pass
            if not self._cookies:
                logger.error("No cookies found in login browser")
                return False
            self._save_cookies()
            logger.info("Captured %d cookies from interactive login", len(self._cookies))
            return True
        except Exception as e:
            logger.error("capture_cookies_from_login failed: %s", e)
            return False
        finally:
            try:
                context.close()
            except Exception:
                pass
            try:
                pw.stop()
            except Exception:
                pass

    def has_cookies(self) -> bool:
        """True if cookies are loaded in memory (does not validate them)."""
        return bool(self._cookies)

    def test_cookies(self) -> bool:
        """Ping the API with current cookies to verify they are still valid.

        Does NOT trigger a browser refresh on failure — purely a status check.
        Returns True if a minimal GraphQL query returns 200 with non-empty data.
        """
        if not self._cookies:
            return False
        from urllib.parse import unquote
        try:
            data_str = unquote(self._cookies.get("_factorial_data", "{}"))
            access_id = str(json.loads(data_str).get("access_id", "")) if data_str else ""
        except Exception:
            access_id = ""
        if not access_id:
            return False

        headers = {
            **REQUIRED_HEADERS,
            "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
        }
        payload = {
            "operationName": "GetEmployeeByAccess",
            "variables": {"accessIds": [access_id]},
            "query": self.EMPLOYEE_ID_QUERY,
        }
        try:
            resp = self._session.post(
                GRAPHQL_URL,
                params=[("operationName", "GetEmployeeByAccess")],
                json=payload,
                headers=headers,
                cookies=self._cookies,
                timeout=API_TIMEOUT,
            )
            if resp.status_code != 200:
                return False
            body = resp.json()
            nodes = body.get("data", {}).get("employees", {}).get("employeesConnection", {}).get("nodes", [])
            return bool(nodes)
        except Exception as e:
            logger.debug("test_cookies failed: %s", e)
            return False

    def clock_in(self) -> bool:
        """Clock in (Fichar)."""
        logger.info("API: clock_in")
        result = self._graphql_request("ClockIn", CLOCK_IN_MUTATION, {
            "now": self._now_iso(),
            "date": self._today_iso(),
            "source": "desktop",
        })
        return result is not None

    def clock_out(self) -> bool:
        """Clock out (Salida)."""
        logger.info("API: clock_out")
        result = self._graphql_request("ClockOut", CLOCK_OUT_MUTATION, {
            "now": self._now_iso(),
            "date": self._today_iso(),
            "source": "desktop",
            "endOn": self._today_iso(),
            "startOn": self._today_iso(),
        })
        return result is not None

    def break_start(self) -> bool:
        """Start break (Pausar)."""
        logger.info("API: break_start")
        result = self._graphql_request("BreakStart", BREAK_START_MUTATION, {
            "now": self._now_iso(),
            "date": self._today_iso(),
            "source": "desktop",
            "timeSettingsBreakConfigurationId": BREAK_CONFIGURATION_ID,
            "endOn": self._today_iso(),
            "startOn": self._today_iso(),
        })
        return result is not None

    def break_end(self) -> bool:
        """End break (Reanudar)."""
        logger.info("API: break_end")
        result = self._graphql_request("BreakEnd", BREAK_END_MUTATION, {
            "now": self._now_iso(),
            "date": self._today_iso(),
            "source": "desktop",
            "systemCreated": False,
            "endOn": self._today_iso(),
            "startOn": self._today_iso(),
        })
        return result is not None

    def get_current_state(self) -> Optional[str]:
        """Query the current open shift to determine clock-in state.

        Returns: "not_clocked_in", "clocked_in", "on_break", or None on error.
        """
        result = self._graphql_request("OpenShifts", OPEN_SHIFT_QUERY, {})
        if result is None:
            return None

        try:
            nodes = result["data"]["attendance"]["openShiftsConnection"]["nodes"]
            if not nodes:
                return "not_clocked_in"

            open_shift = nodes[0]
            # If clocked in but not clocked out
            if open_shift.get("clockIn") and not open_shift.get("clockOut"):
                break_config = open_shift.get("timeSettingsBreakConfiguration")
                if break_config:
                    return "on_break"
                return "clocked_in"

            return "not_clocked_in"
        except (KeyError, TypeError) as e:
            logger.error("Failed to parse open shift state: %s", e)
            return None

    # ── High-level action dispatcher ───────────────────────────────────

    def perform_action(self, action: str, max_retries: int = 2) -> bool:
        """Execute a clock-in action via API with retry."""
        action_map = {
            "fichar":   self.clock_in,
            "pausar":   self.break_start,
            "reanudar": self.break_end,
            "salida":   self.clock_out,
        }

        if action not in action_map:
            logger.error("Unknown action: %s", action)
            return False

        fn = action_map[action]
        for attempt in range(1, max_retries + 1):
            try:
                success = fn()
                if success:
                    logger.info("Action '%s' succeeded (attempt %d)", action, attempt)
                    return True
                logger.warning("Action '%s' returned failure (attempt %d/%d)", action, attempt, max_retries)
            except Exception as e:
                logger.error("Action '%s' threw exception (attempt %d/%d): %s", action, attempt, max_retries, e)

            if attempt < max_retries:
                logger.info("Retrying in %ds...", ACTION_RETRY_DELAY)
                time_module.sleep(ACTION_RETRY_DELAY)

        notify_action_failed()
        return False

    def execute_smart_action(self, action: str) -> bool:
        """Perform action with state-aware validation."""
        current_state = self.get_current_state()
        logger.info("Current state: %s, requested action: %s", current_state, action)

        if current_state is None:
            logger.warning("Cannot determine state — attempting action anyway")

        elif action == "fichar" and current_state in ("clocked_in", "on_break"):
            logger.info("Already clocked in — marking fichar as completed")
            return True

        elif action == "pausar" and current_state == "not_clocked_in":
            logger.warning("Cannot pause — not clocked in!")
            return False

        elif action == "reanudar" and current_state == "clocked_in":
            logger.info("Not on break — marking reanudar as completed")
            return True

        elif action == "salida" and current_state == "not_clocked_in":
            logger.warning("Cannot clock out — not clocked in!")
            return False

        return self.perform_action(action)

    # ── Backfill (past shifts) ─────────────────────────────────────────

    CREATE_SHIFT_MUTATION = """
mutation CreateAttendanceShift($clockIn: ISO8601DateTime, $clockOut: ISO8601DateTime, $date: ISO8601Date!, $employeeId: ID!, $halfDay: String, $locationType: AttendanceShiftLocationTypeEnum, $observations: String, $referenceDate: ISO8601Date!, $source: AttendanceEnumsShiftSourceEnum, $timeSettingsBreakConfigurationId: ID, $workable: Boolean) {
  attendanceMutations {
    createAttendanceShift(
      clockIn: $clockIn
      clockOut: $clockOut
      date: $date
      employeeId: $employeeId
      halfDay: $halfDay
      locationType: $locationType
      observations: $observations
      referenceDate: $referenceDate
      source: $source
      timeSettingsBreakConfigurationId: $timeSettingsBreakConfigurationId
      workable: $workable
    ) {
      errors {
        ... on SimpleError { message type __typename }
        ... on StructuredError { field messages __typename }
        __typename
      }
      shift {
        employee { id __typename }
        id clockIn clockOut date
        __typename
      }
      __typename
    }
    __typename
  }
}
"""

    SHIFTS_QUERY = """
query ShiftsQuery($endOn: ISO8601Date!, $startOn: ISO8601Date!, $employeeId: ID!) {
  attendance {
    employee(id: $employeeId) {
      id
      attendanceShiftsConnection(endOn: $endOn, startOn: $startOn) {
        nodes {
          id clockIn clockOut date workable
          timeSettingsBreakConfiguration { id name paid }
        }
      }
    }
  }
}
"""

    EMPLOYEE_ID_QUERY = """
query GetEmployeeByAccess($accessIds: [ID!]!) {
  employees {
    employeesConnection(accessIds: $accessIds, first: 1) {
      nodes {
        id
      }
    }
  }
}
"""

    def _get_employee_id(self) -> Optional[str]:
        """Fetch the current employee ID using access_id from cookies."""
        # Try to get access_id from _factorial_data cookie
        access_id = None
        from urllib.parse import unquote
        data_str = unquote(self._cookies.get("_factorial_data", "{}"))
        try:
            data = json.loads(data_str)
            access_id = str(data.get("access_id", ""))
        except (json.JSONDecodeError, TypeError):
            pass

        if not access_id:
            logger.error("No access_id found in cookies — cannot determine employee ID")
            return None

        result = self._graphql_request(
            "GetEmployeeByAccess",
            self.EMPLOYEE_ID_QUERY,
            {"accessIds": [access_id]},
        )
        if result is None:
            return None
        try:
            nodes = result["data"]["employees"]["employeesConnection"]["nodes"]
            if nodes:
                employee_id = nodes[0]["id"]
                logger.info("Employee ID: %s", employee_id)
                return employee_id
            logger.error("No employee found for access_id %s", access_id)
            return None
        except (KeyError, TypeError) as e:
            logger.error("Failed to parse employee ID: %s", e)
            return None

    def get_shifts_for_range(self, start_date: date, end_date: date, employee_id: Optional[str] = None) -> dict[str, list[dict]]:
        """Get all shifts for a date range, grouped by date.

        Returns dict: {date_string: [{clockIn, clockOut, workable, ...}, ...]}
        """
        if not employee_id:
            employee_id = self._get_employee_id()
        if not employee_id:
            logger.error("Cannot fetch shifts — no employee ID")
            return {}

        result = self._graphql_request(
            "ShiftsQuery",
            self.SHIFTS_QUERY,
            {
                "startOn": start_date.isoformat(),
                "endOn": end_date.isoformat(),
                "employeeId": employee_id,
            },
        )
        if result is None:
            return {}

        try:
            shifts = result["data"]["attendance"]["employee"]["attendanceShiftsConnection"]["nodes"]
            by_date: dict[str, list[dict]] = {}
            for s in shifts:
                d = s["date"]
                if d not in by_date:
                    by_date[d] = []
                by_date[d].append(s)
            return by_date
        except (KeyError, TypeError) as e:
            logger.error("Failed to parse shifts: %s", e)
            return {}

    def _calculate_worked_minutes(self, shifts: list[dict]) -> float:
        """Calculate total worked minutes from a list of shifts."""
        total = 0.0
        for s in shifts:
            if s.get("clockIn") and s.get("clockOut"):
                # Parse ISO datetime strings
                cin = datetime.fromisoformat(s["clockIn"].replace("Z", "+00:00"))
                cout = datetime.fromisoformat(s["clockOut"].replace("Z", "+00:00"))
                total += (cout - cin).total_seconds() / 60
        return total

    def _normalize_shift_slot(self, shift: dict) -> Optional[tuple[str, str, bool]]:
        """Convert an existing shift into a comparable (clock_in, clock_out, is_break) tuple."""
        if not shift.get("clockIn") or not shift.get("clockOut"):
            return None

        try:
            cin = datetime.fromisoformat(shift["clockIn"].replace("Z", "+00:00")).astimezone(TZ)
            cout = datetime.fromisoformat(shift["clockOut"].replace("Z", "+00:00")).astimezone(TZ)
        except ValueError:
            return None

        break_config = shift.get("timeSettingsBreakConfiguration")
        is_break = bool(break_config) or shift.get("workable") is False
        return (cin.strftime("%H:%M"), cout.strftime("%H:%M"), is_break)

    def _get_missing_shift_slots(self, shifts: list[dict], target_date: str) -> list[tuple[str, str, str, bool]]:
        """Return expected slots that are missing for the target date."""
        target_d = date.fromisoformat(target_date)
        expected_slots = get_shift_slots_for_date(target_d)
        existing_slots = {
            slot for shift in shifts
            if (slot := self._normalize_shift_slot(shift)) is not None
        }

        missing = [
            (label, clock_in, clock_out, is_break)
            for label, clock_in, clock_out, is_break in expected_slots
            if (clock_in, clock_out, is_break) not in existing_slots
        ]

        worked = self._calculate_worked_minutes(shifts)
        expected_minutes = get_expected_work_minutes_for_date(target_d)
        logger.info(
            "Date %s status: %d/%d expected slots present, %.0f/%d min worked, missing=%s",
            target_date,
            len(expected_slots) - len(missing),
            len(expected_slots),
            worked,
            expected_minutes,
            [label for label, _, _, _ in missing] or ["none"],
        )
        return missing

    def _shifts_match_expected(self, shifts: list[dict], target_date: str) -> bool:
        """Check if existing shifts already match the configured schedule."""
        missing = self._get_missing_shift_slots(shifts, target_date)
        if not missing:
            logger.info("Date %s already matches expected slots — skipping", target_date)
            return True
        return False

    def create_shift(
        self,
        target_date: str,
        clock_in: str,
        clock_out: str,
        employee_id: str,
        is_break: bool = False,
    ) -> bool:
        """Create a single shift entry for a past date.

        Args:
            target_date: ISO date string (e.g. "2026-04-21")
            clock_in: Time string like "09:00"
            clock_out: Time string like "14:00"
            employee_id: The employee ID
            is_break: If True, this is a break/pause shift
        """
        tz_offset = self._get_tz_offset(target_date)
        clock_in_iso = f"{target_date}T{clock_in}:00{tz_offset}"
        clock_out_iso = f"{target_date}T{clock_out}:00{tz_offset}"

        from config import BREAK_CONFIGURATION_ID

        variables = {
            "date": target_date,
            "employeeId": employee_id,
            "clockIn": clock_in_iso,
            "clockOut": clock_out_iso,
            "referenceDate": target_date,
            "source": "desktop",
            "timeSettingsBreakConfigurationId": BREAK_CONFIGURATION_ID if is_break else None,
            "workable": not is_break,
        }

        logger.info("Creating shift: %s %s-%s (%s)", target_date, clock_in, clock_out, "pausa" if is_break else "trabajo")
        result = self._graphql_request("CreateAttendanceShift", self.CREATE_SHIFT_MUTATION, variables)
        return result is not None

    def _get_tz_offset(self, target_date_str: str) -> str:
        """Get the timezone offset for a given date (handles DST)."""
        d = date.fromisoformat(target_date_str)
        dt = datetime(d.year, d.month, d.day, 12, 0, tzinfo=TZ)
        offset = dt.strftime("%z")
        # Format like "+02:00" from "+0200"
        if len(offset) == 5:
            return f"{offset[:3]}:{offset[3:]}"
        return "+02:00"  # default CET

    def backfill_date(self, target_date: str, employee_id: Optional[str] = None) -> bool:
        """Fill a single past date with the configured shift schedule."""
        if not employee_id:
            employee_id = self._get_employee_id()
        if not employee_id:
            logger.error("Cannot backfill — no employee ID")
            return False

        # Check which slots are missing for this date
        target_d = date.fromisoformat(target_date)
        existing = self.get_shifts_for_range(target_d, target_d, employee_id)
        shifts = existing.get(target_date, [])

        missing_slots = self._get_missing_shift_slots(shifts, target_date)
        if not missing_slots:
            return True  # already filled

        if shifts:
            logger.warning(
                "Date %s has partial shifts (%.0f min) — will add missing slots: %s",
                target_date,
                self._calculate_worked_minutes(shifts),
                [label for label, _, _, _ in missing_slots],
            )
        else:
            logger.info(
                "Date %s has no shifts — will create all expected slots: %s",
                target_date,
                [label for label, _, _, _ in missing_slots],
            )

        all_ok = True
        for label, clock_in, clock_out, is_break in missing_slots:
            ok = self.create_shift(target_date, clock_in, clock_out, employee_id, is_break=is_break)
            if ok:
                logger.info("  Created %s: %s-%s ✓", label, clock_in, clock_out)
            else:
                logger.error("  Failed to create %s: %s-%s ✗", label, clock_in, clock_out)
                all_ok = False
            time_module.sleep(1)  # small delay between creates

        return all_ok

    def backfill_week(self, days_back: int = 7) -> dict[str, bool]:
        """Backfill all workdays in the past N days that have missing hours.

        Returns dict: {date_string: success_bool}
        """
        from holidays import is_workday

        employee_id = self._get_employee_id()
        if not employee_id:
            logger.error("Cannot backfill week — no employee ID")
            return {}

        today = date.today()
        start = today - timedelta(days=days_back)
        end = today - timedelta(days=1)  # don't include today

        # Get existing shifts for the range
        existing = self.get_shifts_for_range(start, end, employee_id)

        results = {}
        current = start
        while current <= end:
            date_str = current.isoformat()

            if not is_workday(current):
                logger.info("Skipping %s — not a workday", date_str)
                current += timedelta(days=1)
                continue

            shifts = existing.get(date_str, [])
            if self._shifts_match_expected(shifts, date_str):
                results[date_str] = True  # already complete
            else:
                logger.info("Backfilling %s (%.0f min worked)", date_str, self._calculate_worked_minutes(shifts))
                results[date_str] = self.backfill_date(date_str, employee_id)

            current += timedelta(days=1)

        # Summary
        filled = sum(1 for v in results.values() if v)
        total = len(results)
        logger.info("Backfill complete: %d/%d dates filled", filled, total)

        return results
