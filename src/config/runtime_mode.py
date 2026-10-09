"""Runtime selection for the desktop application."""
from __future__ import annotations

import os


LOCAL = "local"
CLOUD = "cloud"


def get_runtime_mode() -> str:
    """Return the supported runtime mode, defaulting safely to local."""
    value = (os.getenv("FALAI_RUNTIME_MODE", LOCAL) or LOCAL).strip().lower()
    return CLOUD if value == CLOUD else LOCAL


def is_local_runtime() -> bool:
    return get_runtime_mode() == LOCAL
