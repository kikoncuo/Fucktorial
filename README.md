# Fucktorial

> A tiny act of protest against Factorial HR's clock-in UX, disguised as a Python automation.

Factorial is a time-tracking tool that, for reasons that can only be explained by someone being paid per click, requires you to perform roughly **six clicks per "turn"**, and there are **three turns a day** (clock in, pause, resume, clock out). That's ~18 clicks a day, every day, to tell a computer the same thing you told it yesterday.

And because it would be *too easy* to just "fill the whole week on Monday morning," the UI politely refuses to let you edit more than one day at a time. You have to show up. Every. Single. Day. Right at 9:00. And again at 14:00. And again at 14:30. And again at 18:00.

God forbid you go grab lunch, or actually finish work, or — heaven help you — have a meeting that runs over. Miss a turn and now you get to manually backfill it from the web UI, through a modal that opens, closes, re-opens, and asks you to confirm the timezone for some reason.

**Fucktorial clicks the buttons so you don't have to.**

It talks directly to Factorial's GraphQL API (no janky browser automation in the hot path), runs as a quiet little daemon in the background, and does the needful at the scheduled times. It can also **backfill** the past N days when you forgot it existed / were on holiday / your laptop died / you simply refused to participate.

---

## How it works

1. **Cookies** are grabbed once from your Chrome profile via Playwright, saved to `factorial_cookies.json`, and reused for API calls. No password handling, no 2FA dance — if your browser is logged in, the script is logged in.
2. The **scheduler** wakes up periodically (every 30s by default), checks the schedule for today, and fires the next pending action if it's due.
3. Each action (`fichar`, `pausar`, `reanudar`, `salida`) is a single GraphQL mutation. It's fast, it's boring, it works.
4. State is kept in `clock_state.json` so you can restart the daemon without double-firing.
5. There's a 30-minute **grace window**: if you were offline when 9:00 hit, it'll still clock you in at 9:17 when your laptop wakes up. Past that window, the action is marked "missed" and the Mac plays a sad sound at you.
6. Holidays and weekends are respected (see `holidays.py`). It won't clock you in on Christmas.

---

## Install

Requires **Python 3.11+** and **macOS** (for the system sounds — the rest is cross-platform-ish).

```bash
git clone https://github.com/kikoncuo/Fucktorial.git
cd Fucktorial
pip install -r requirements.txt
python -m playwright install chromium
```

Dependencies are:
- `requests` — to talk to the GraphQL endpoint
- `playwright` — only used once in a while to refresh cookies from your browser

The script will `pip install` these itself on first run if they're missing, but do it properly.

---

## One-time setup

1. Log into Factorial in Chrome as you normally would.
2. Run the cookie refresh:

   ```bash
   python main.py --refresh
   ```

   A Chromium window opens, logs into Factorial using your existing browser session (via a persistent `browser_data/` profile), grabs the cookies it needs, and closes. You should only have to do this when cookies expire (~every 12h by default, controlled by `COOKIES_STALE_AFTER_HOURS`).

3. Edit `config.py` and set `COMPANY_NAME` to whatever your Factorial company is called. It's set to `Laberit Sistemas S.L.` by default because that's where this was written — change it or the company selector page will haunt you.

---

## Running it

### Live / daemon mode (the whole point)

```bash
python main.py                           # default: friday-6h schedule
python main.py --schedule                # same as above, explicit
python main.py --schedule-mode standard  # 9-14, 14:30-18 every weekday
```

The process locks itself via `factorial.lock` so you can't accidentally run two. Leave it running in a terminal, a `tmux` session, a `launchd` plist, a `screen`, a `nohup &`, whatever pleases your operational soul.

### Immediate action

```bash
python main.py --now            # run the next pending action right now
python main.py --force fichar   # clock in NOW, regardless of schedule
python main.py --force pausar   # start break
python main.py --force reanudar # end break
python main.py --force salida   # clock out
```

Useful when you're leaving early, came in late, or just want to prove to yourself the thing works.

### Backfill mode (the redemption arc)

```bash
python main.py --backfill        # fill the last 7 days
python main.py --backfill 14     # fill the last 14 days
python main.py --backfill 30     # you hedonist
```

It walks each workday backwards, skips weekends and holidays, skips days that already have shifts, and posts the expected slots (full day, or `09:00–15:00` on Fridays in `friday-6h` mode). Came back from a week off and Factorial is glaring at you? `--backfill 10` and go make coffee.

### Cookie refresh only

```bash
python main.py --refresh
```

Use when the API starts returning 401s.

---

## Settings

All in `config.py`:

| Setting | What it does |
|---|---|
| `DEFAULT_SCHEDULE` | The standard weekday shape: `fichar 09:00 · pausar 14:00 · reanudar 14:30 · salida 18:00` |
| `FRIDAY_SCHEDULE_6H` | Friday short day: `fichar 09:00 · salida 15:00` |
| `DEFAULT_SCHEDULE_MODE` | `friday-6h` (default) or `standard` |
| `STANDARD_SHIFT_SLOTS` / `FRIDAY_SHIFT_SLOTS_6H` | What backfill posts |
| `GRACE_WINDOW_MINUTES` | How late an action can still fire (default `30`) |
| `SLEEP_INTERVAL_SECONDS` | Scheduler poll interval (default `30`) |
| `COOKIES_STALE_AFTER_HOURS` | Auto-refresh cookies after this (default `12`) |
| `TIMEZONE` | `Europe/Madrid` — change if you work elsewhere |
| `COMPANY_NAME` | Your Factorial tenant name |
| `BREAK_CONFIGURATION_ID` | The `break_configuration_id` captured from a real session. If breaks stop registering, re-capture this from DevTools → Network. |
| `SOUND_*` | macOS system sounds for login-needed / completed / missed / failed |

---

## Files it writes

- `factorial_cookies.json` — your session. **Do not commit this.**
- `clock_state.json` — what's been done today.
- `factorial.log` — every decision it made, for when you want to prove it's the script's fault.
- `factorial.lock` — mutex; delete only if you're sure nothing's running.
- `browser_data/` — Playwright's persistent Chromium profile, so you don't re-login constantly.
- `local_holidays.json` (optional) — extra holidays beyond the built-in list.

---

## FAQ

**Is this against the Factorial ToS?**
Probably. It's also against my will to click the same button 90 times a week. We all have our crosses to bear.

**Will I get fired?**
Only if your manager reads this README. If they do, hi, the script accurately reflects my actual working hours, which is more than can be said for the UI that expected me to log them in real-time while also, you know, working.

**Why can't I just edit the whole week in one go in Factorial's UI?**
Excellent question. Please forward it to Factorial.

**Why the name?**
It wrote itself.

---

## Disclaimer

This is a personal automation script that performs actions you're allowed to perform manually. It logs actual hours; it doesn't forge them. Use it responsibly, don't clock in for shifts you didn't work, and don't blame me when Factorial changes their GraphQL schema and everything breaks on a Tuesday morning.
