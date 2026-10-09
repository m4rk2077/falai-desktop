"""
Filesystem locations for FALAI (user-writable).

Why this exists:
- When the app is packaged as a Windows installer (setup.exe), the install folder is usually
  under Program Files and is NOT writable for normal users.
- Logs, settings, history must live in a per-user directory (APPDATA/LOCALAPPDATA).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


APP_DIR_NAME = "FALAI"


def get_app_data_dir() -> Path:
    """Return a user-writable directory for app data."""
    if sys.platform == "win32":
        base = os.getenv("APPDATA") or os.getenv("LOCALAPPDATA")
        if base:
            return Path(base) / APP_DIR_NAME
        # Fallback (rare): derive from HOME
        return Path.home() / "AppData" / "Roaming" / APP_DIR_NAME

    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_DIR_NAME

    # Linux / other
    xdg = os.getenv("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / APP_DIR_NAME.lower()
    return Path.home() / ".local" / "share" / APP_DIR_NAME.lower()


def ensure_app_data_dir() -> Path:
    p = get_app_data_dir()
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_config_path() -> Path:
    return ensure_app_data_dir() / "config.json"


def get_history_path() -> Path:
    return ensure_app_data_dir() / "history.enc"


def get_legacy_history_path() -> Path:
    """Legacy plaintext history path kept only for migration."""
    return ensure_app_data_dir() / "history.json"


def get_sync_queue_path() -> Path:
    return ensure_app_data_dir() / "sync_queue.json"


def get_outbox_path() -> Path:
    """Queue file for offline items (audio + telemetry)."""
    return ensure_app_data_dir() / "outbox.enc"


def get_legacy_outbox_path() -> Path:
    """Legacy plaintext outbox path kept only for migration."""
    return ensure_app_data_dir() / "outbox.json"


def get_outbox_audio_dir() -> Path:
    """Directory that holds queued WAV files for offline transcription."""
    p = ensure_app_data_dir() / "outbox_audio"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_updates_dir() -> Path:
    """Directory that holds downloaded update installers (setup.exe)."""
    p = ensure_app_data_dir() / "updates"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_log_dir() -> Path:
    p = ensure_app_data_dir() / "logs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_log_path() -> Path:
    return get_log_dir() / "falai.log"
