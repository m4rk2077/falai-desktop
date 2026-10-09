"""Transcription repository with local sync queue support."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.backend.supabase_client import SupabaseClient
from src.utils.app_paths import get_sync_queue_path


class TranscriptionRepo:
    def __init__(self, client: SupabaseClient, queue_file: str | Path | None = None):
        self.client = client
        self.queue_file = Path(queue_file) if queue_file is not None else get_sync_queue_path()

    def enqueue(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        queue = self._load_queue()
        item = {
            "id": len(queue) + 1,
            "type": "transcription",
            "status": "pending",
            "retry_count": 0,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "payload": payload,
        }
        queue.append(item)
        self._save_queue(queue)
        return item

    def sync_pending(self, access_token: str, max_items: int = 50) -> Dict[str, int]:
        queue = self._load_queue()
        synced = 0
        failed = 0

        for item in queue[:max_items]:
            if item.get("status") != "pending":
                continue
            try:
                self.client.table_insert("transcriptions", item["payload"], jwt=access_token)
                item["status"] = "synced"
                item["synced_at"] = datetime.now(timezone.utc).isoformat()
                synced += 1
            except Exception as exc:
                item["status"] = "failed"
                item["retry_count"] = int(item.get("retry_count", 0)) + 1
                item["last_error"] = str(exc)
                failed += 1

        self._save_queue(queue)
        return {"synced": synced, "failed": failed, "total": len(queue)}

    def create_remote(self, payload: Dict[str, Any], access_token: str):
        return self.client.table_insert("transcriptions", payload, jwt=access_token)

    def _load_queue(self) -> List[Dict[str, Any]]:
        try:
            if self.queue_file.exists():
                with open(self.queue_file, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            return []
        return []

    def _save_queue(self, queue: List[Dict[str, Any]]) -> None:
        os.makedirs(self.queue_file.parent, exist_ok=True)
        with open(self.queue_file, "w", encoding="utf-8") as f:
            json.dump(queue, f, ensure_ascii=False, indent=2)
