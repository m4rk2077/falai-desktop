"""
Simple sound effects for recording feedback (Windows).
"""
from __future__ import annotations

import sys
from pathlib import Path

from src.utils.logger import get_logger

logger = get_logger(__name__)

_ROOT = Path(__file__).resolve().parents[3]
_SOUNDS_DIR = _ROOT / "assets" / "sounds"
_SOUNDS = {
    "start": _SOUNDS_DIR / "start.wav",
    "stop": _SOUNDS_DIR / "stop.wav",
    "error": _SOUNDS_DIR / "error.wav",
}


def _beep(freq: int, dur_ms: int):
    if sys.platform != "win32":
        return
    try:
        import winsound
        winsound.Beep(freq, dur_ms)
    except Exception:
        logger.debug("Beep failed", exc_info=True)


def _play_wav(name: str, fallback_freq: int, fallback_dur: int):
    if sys.platform != "win32":
        return
    try:
        import winsound
        path = _SOUNDS.get(name)
        if path and path.exists():
            winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)
        else:
            logger.debug("Sound file missing: %s", path)
            _beep(fallback_freq, fallback_dur)
    except Exception:
        logger.debug("PlaySound failed", exc_info=True)
        _beep(fallback_freq, fallback_dur)


def play_start():
    _play_wav("start", 1100, 60)


def play_stop():
    _play_wav("stop", 800, 60)


def play_error():
    _play_wav("error", 330, 120)
