"""Background sync worker for local queue -> Supabase."""
from __future__ import annotations

import threading
import time
from typing import Optional

from src.utils.logger import get_logger

logger = get_logger(__name__)


class SyncWorker:
    def __init__(self, transcription_repo, get_access_token, interval_seconds: int = 30):
        self.transcription_repo = transcription_repo
        self.get_access_token = get_access_token
        self.interval_seconds = interval_seconds
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info("SyncWorker started (interval=%ss)", self.interval_seconds)

    def stop(self):
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        logger.info("SyncWorker stopped")

    def trigger_once(self):
        self._sync_once()

    def _run(self):
        while not self._stop_event.is_set():
            self._sync_once()
            self._stop_event.wait(self.interval_seconds)

    def _sync_once(self):
        token = self.get_access_token() if callable(self.get_access_token) else ""
        if not token:
            return
        try:
            result = self.transcription_repo.sync_pending(access_token=token)
            if result.get("synced") or result.get("failed"):
                logger.info("SyncWorker result: %s", result)
        except Exception:
            logger.error("SyncWorker cycle failed", exc_info=True)
