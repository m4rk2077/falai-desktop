"""Offline outbox queue for client -> backend operations.

This queue is used for:
- edge_transcribe: store WAV locally and send to Supabase Edge Function when online
- edge_postprocess: async correction/refinement for server transcription
- client_event: store telemetry events and send to PostgREST when online

Important:
- This file stores *user audio* temporarily when offline. We keep strict limits + TTL.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.security.local_crypto import LocalCrypto, LocalCryptoError


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso_to_epoch(value: str) -> Optional[float]:
    try:
        dt = datetime.fromisoformat(str(value))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        return None


@dataclass
class OutboxLimits:
    max_items: int = 20
    max_total_bytes: int = 50 * 1024 * 1024  # 50 MB
    ttl_days: int = 7


class OutboxRepo:
    def __init__(self, outbox_path: Path, audio_dir: Path, *, limits: Optional[OutboxLimits] = None):
        self.outbox_path = Path(outbox_path)
        self.legacy_outbox_path = self.outbox_path.with_suffix(".json")
        self.audio_dir = Path(audio_dir)
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        self.limits = limits or OutboxLimits()
        self.crypto = LocalCrypto()
        self._lock = threading.Lock()
        self._migrate_legacy_storage()

    def _migrate_legacy_storage(self) -> None:
        try:
            # Migrate plaintext outbox JSON -> encrypted outbox file.
            self.crypto.migrate_json_file(self.legacy_outbox_path, self.outbox_path, default_obj=[])

            # Migrate any leftover plaintext WAV files.
            for wav in self.audio_dir.glob("*.wav"):
                self.crypto.migrate_binary_file(wav, wav.with_suffix(".enc"))
        except Exception as exc:
            raise LocalCryptoError("Outbox secure migration failed.") from exc

    def _load_items_unlocked(self) -> List[Dict[str, Any]]:
        try:
            if not self.outbox_path.exists():
                return []
            obj = self.crypto.read_json(self.outbox_path, default=[])
            if isinstance(obj, list):
                return [x for x in obj if isinstance(x, dict)]
            return []
        except Exception:
            # If file is corrupted, we don't want to crash the app. Start fresh.
            return []

    def _save_items_unlocked(self, items: List[Dict[str, Any]]) -> None:
        self.outbox_path.parent.mkdir(parents=True, exist_ok=True)
        self.crypto.write_json(self.outbox_path, items)

    def _audio_path(self, item_id: str) -> Path:
        return self.audio_dir / f"{item_id}.enc"

    def _legacy_audio_path(self, item_id: str) -> Path:
        return self.audio_dir / f"{item_id}.wav"

    def prune_expired(self) -> int:
        """Remove items older than TTL (and delete any attached WAV)."""
        with self._lock:
            items = self._load_items_unlocked()
            if not items:
                return 0

            ttl_seconds = int(self.limits.ttl_days) * 24 * 3600
            now = time.time()

            kept: List[Dict[str, Any]] = []
            removed = 0
            for it in items:
                created_at = it.get("created_at", "")
                created_epoch = _parse_iso_to_epoch(str(created_at)) or 0.0
                if created_epoch and (now - created_epoch) > ttl_seconds:
                    removed += 1
                    if it.get("type") == "edge_transcribe":
                        try:
                            self._audio_path(str(it.get("id") or "")).unlink(missing_ok=True)  # py>=3.8
                        except Exception:
                            pass
                        try:
                            self._legacy_audio_path(str(it.get("id") or "")).unlink(missing_ok=True)
                        except Exception:
                            pass
                    continue
                kept.append(it)

            if removed:
                self._save_items_unlocked(kept)
            return removed

    def _current_audio_bytes_unlocked(self, items: List[Dict[str, Any]]) -> int:
        total = 0
        for it in items:
            if it.get("type") != "edge_transcribe":
                continue
            item_id = str(it.get("id") or "").strip()
            if not item_id:
                continue
            try:
                total += int(self._audio_path(item_id).stat().st_size)
            except Exception:
                continue
        return total

    def _drop_oldest_pending_unlocked(self, items: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
        pending = [it for it in items if str(it.get("status") or "pending") == "pending"]
        if not pending:
            return items, None

        def _sort_key(it: Dict[str, Any]) -> float:
            return _parse_iso_to_epoch(str(it.get("created_at") or "")) or 0.0

        oldest = sorted(pending, key=_sort_key)[0]
        oldest_id = str(oldest.get("id") or "").strip()
        kept = [it for it in items if str(it.get("id") or "") != oldest_id]

        if oldest.get("type") == "edge_transcribe" and oldest_id:
            try:
                self._audio_path(oldest_id).unlink(missing_ok=True)
            except Exception:
                pass
            try:
                self._legacy_audio_path(oldest_id).unlink(missing_ok=True)
            except Exception:
                pass

        return kept, oldest

    def _enqueue_drop_event_unlocked(self, items: List[Dict[str, Any]], dropped: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Record a local client_event when we drop a pending item due to limits."""
        try:
            evt = {
                "id": str(uuid.uuid4()),
                "type": "client_event",
                "status": "pending",
                "created_at": _utc_now_iso(),
                "attempts": 0,
                "next_attempt_at": 0,
                "last_error": "",
                "payload": {
                    "event_type": "outbox_dropped_oldest",
                    "severity": "warning",
                    "message": "Outbox cheia; descartamos o item mais antigo.",
                    "details": {
                        "dropped_id": str(dropped.get("id") or ""),
                        "dropped_type": str(dropped.get("type") or ""),
                    },
                },
            }
            items.append(evt)
        except Exception:
            pass
        return items

    def _enforce_limits_unlocked(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        # Enforce item count.
        while len(items) > int(self.limits.max_items):
            items, dropped = self._drop_oldest_pending_unlocked(items)
            if not dropped:
                break
            items = self._enqueue_drop_event_unlocked(items, dropped)

        # Enforce total audio bytes.
        max_bytes = int(self.limits.max_total_bytes)
        while self._current_audio_bytes_unlocked(items) > max_bytes:
            items, dropped = self._drop_oldest_pending_unlocked(items)
            if not dropped:
                break
            items = self._enqueue_drop_event_unlocked(items, dropped)

        return items

    def add_edge_transcribe(self, wav_bytes: bytes, payload: Dict[str, Any]) -> str:
        item_id = str(uuid.uuid4())
        audio_path = self._audio_path(item_id)
        audio_path.parent.mkdir(parents=True, exist_ok=True)
        self.crypto.write_bytes(audio_path, wav_bytes)

        item = {
            "id": item_id,
            "type": "edge_transcribe",
            "status": "pending",
            "created_at": _utc_now_iso(),
            "attempts": 0,
            "next_attempt_at": 0,
            "last_error": "",
            "payload": dict(payload or {}),
        }

        with self._lock:
            items = self._load_items_unlocked()
            # Prune first to free space.
            items = self._enforce_limits_unlocked(items)
            items.append(item)
            items = self._enforce_limits_unlocked(items)
            self._save_items_unlocked(items)

        return item_id

    def add_client_event(self, payload: Dict[str, Any]) -> str:
        item_id = str(uuid.uuid4())
        item = {
            "id": item_id,
            "type": "client_event",
            "status": "pending",
            "created_at": _utc_now_iso(),
            "attempts": 0,
            "next_attempt_at": 0,
            "last_error": "",
            "payload": dict(payload or {}),
        }
        with self._lock:
            items = self._load_items_unlocked()
            items = self._enforce_limits_unlocked(items)
            items.append(item)
            items = self._enforce_limits_unlocked(items)
            self._save_items_unlocked(items)
        return item_id

    def add_edge_postprocess(self, payload: Dict[str, Any]) -> str:
        """Queue an async server-side postprocess for a transcription."""
        item_id = str(uuid.uuid4())
        item = {
            "id": item_id,
            "type": "edge_postprocess",
            "status": "pending",
            "created_at": _utc_now_iso(),
            "attempts": 0,
            "next_attempt_at": 0,
            "last_error": "",
            "payload": dict(payload or {}),
        }
        with self._lock:
            items = self._load_items_unlocked()
            items = self._enforce_limits_unlocked(items)
            items.append(item)
            items = self._enforce_limits_unlocked(items)
            self._save_items_unlocked(items)
        return item_id

    def list_due(self, *, now_epoch: Optional[float] = None, limit: int = 10) -> List[Dict[str, Any]]:
        now = float(now_epoch if now_epoch is not None else time.time())
        with self._lock:
            items = self._load_items_unlocked()
            due = []
            for it in items:
                if str(it.get("status") or "pending") != "pending":
                    continue
                nxt = it.get("next_attempt_at", 0) or 0
                try:
                    if float(nxt) > now:
                        continue
                except Exception:
                    pass
                due.append(it)

            def _sort_key(it: Dict[str, Any]) -> float:
                return _parse_iso_to_epoch(str(it.get("created_at") or "")) or 0.0

            due = sorted(due, key=_sort_key)
            return due[: max(1, int(limit))]

    def get_audio_bytes(self, item_id: str) -> Optional[bytes]:
        try:
            p = self._audio_path(str(item_id))
            if not p.exists():
                legacy = self._legacy_audio_path(str(item_id))
                if not legacy.exists():
                    return None
                # Best-effort one-shot migration of stale plaintext file.
                self.crypto.migrate_binary_file(legacy, p)
            return self.crypto.read_bytes(p)
        except Exception:
            return None

    def mark_attempt(self, item_id: str, *, error: str, next_attempt_at: float, keep_pending: bool = True) -> None:
        with self._lock:
            items = self._load_items_unlocked()
            for it in items:
                if str(it.get("id") or "") != str(item_id):
                    continue
                it["attempts"] = int(it.get("attempts") or 0) + 1
                it["last_error"] = str(error or "")[:500]
                it["next_attempt_at"] = float(next_attempt_at or 0)
                if not keep_pending:
                    it["status"] = "failed"
                break
            self._save_items_unlocked(items)

    def mark_synced(self, item_id: str) -> None:
        with self._lock:
            items = self._load_items_unlocked()
            kept = [it for it in items if str(it.get("id") or "") != str(item_id)]
            self._save_items_unlocked(kept)

        # Delete WAV after we remove from JSON (best-effort).
        try:
            self._audio_path(str(item_id)).unlink(missing_ok=True)
        except Exception:
            pass
        try:
            self._legacy_audio_path(str(item_id)).unlink(missing_ok=True)
        except Exception:
            pass
