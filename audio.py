"""Audio notifications — macOS afplay, Windows winsound, silent elsewhere."""

import logging
import subprocess
import sys
import threading
import time
from pathlib import Path

from config import (
    SOUND_LOGIN_NEEDED,
    SOUND_ACTION_COMPLETED,
    SOUND_ACTION_MISSED,
    SOUND_ACTION_FAILED,
)

logger = logging.getLogger("audio")
_IS_MAC = sys.platform == "darwin"
_IS_WIN = sys.platform == "win32"


def _play_once_mac(sound_path: str) -> None:
    try:
        subprocess.run(
            ["afplay", sound_path],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        logger.warning("afplay not found — cannot play sound")


def _play_once_windows(tone: str) -> None:
    try:
        import winsound
        mapping = {
            "login": "SystemExclamation",
            "completed": "SystemAsterisk",
            "missed": "SystemHand",
            "failed": "SystemHand",
        }
        winsound.PlaySound(mapping.get(tone, "SystemDefault"), winsound.SND_ALIAS)
    except Exception as e:
        logger.debug("winsound failed: %s", e)


def play_sound(sound_path: str, repeat: int = 1, interval: float = 1.0, tone: str = "completed") -> None:
    """Play a notification sound in a background thread.

    macOS: plays `sound_path` via afplay.
    Windows: plays a system alias from `tone`.
    Other: silent.
    """
    if _IS_MAC and not Path(sound_path).exists():
        logger.warning("Sound file not found: %s", sound_path)
        return

    def _play():
        for i in range(repeat):
            if _IS_MAC:
                _play_once_mac(sound_path)
            elif _IS_WIN:
                _play_once_windows(tone)
            else:
                return
            if i < repeat - 1:
                time.sleep(interval)

    threading.Thread(target=_play, daemon=True).start()


def notify_login_needed() -> None:
    logger.info("Playing login-needed sound (3x)")
    play_sound(SOUND_LOGIN_NEEDED, repeat=3, interval=1.0, tone="login")


def notify_action_completed() -> None:
    logger.debug("Playing action-completed sound")
    play_sound(SOUND_ACTION_COMPLETED, repeat=1, tone="completed")


def notify_action_missed() -> None:
    logger.info("Playing action-missed sound (2x)")
    play_sound(SOUND_ACTION_MISSED, repeat=2, interval=0.8, tone="missed")


def notify_action_failed() -> None:
    logger.warning("Playing action-failed sound (3x)")
    play_sound(SOUND_ACTION_FAILED, repeat=3, interval=0.5, tone="failed")
