"""Audio notifications via macOS afplay."""

import logging
import subprocess
import threading
from pathlib import Path

from config import (
    SOUND_LOGIN_NEEDED,
    SOUND_ACTION_COMPLETED,
    SOUND_ACTION_MISSED,
    SOUND_ACTION_FAILED,
)

logger = logging.getLogger("audio")


def play_sound(sound_path: str, repeat: int = 1, interval: float = 1.0) -> None:
    """Play a sound file using macOS afplay in a background thread."""
    if not Path(sound_path).exists():
        logger.warning("Sound file not found: %s", sound_path)
        return

    def _play():
        for i in range(repeat):
            try:
                subprocess.run(
                    ["afplay", sound_path],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except FileNotFoundError:
                logger.warning("afplay not found — cannot play sound")
                break
            if i < repeat - 1:
                import time
                time.sleep(interval)

    thread = threading.Thread(target=_play, daemon=True)
    thread.start()


def notify_login_needed() -> None:
    """Urgent: 3 repeats of Sosumi — user must log in."""
    logger.info("Playing login-needed sound (3x Sosumi)")
    play_sound(SOUND_LOGIN_NEEDED, repeat=3, interval=1.0)


def notify_action_completed() -> None:
    """Subtle: single Glass sound — action succeeded."""
    logger.debug("Playing action-completed sound (1x Glass)")
    play_sound(SOUND_ACTION_COMPLETED, repeat=1)


def notify_action_missed() -> None:
    """Warning: 2 repeats of Basso — an action was missed."""
    logger.info("Playing action-missed sound (2x Basso)")
    play_sound(SOUND_ACTION_MISSED, repeat=2, interval=0.8)


def notify_action_failed() -> None:
    """Error: 3 rapid repeats of Funk — action failed."""
    logger.warning("Playing action-failed sound (3x Funk)")
    play_sound(SOUND_ACTION_FAILED, repeat=3, interval=0.5)
