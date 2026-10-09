"""Repository for lightweight client telemetry events.

We intentionally do NOT ship full client logs by default.
These events are short summaries to help debug beta issues without asking users for files.
"""

from __future__ import annotations

from typing import Any, Dict

from src.backend.supabase_client import SupabaseClient


class ClientEventsRepo:
    def __init__(self, client: SupabaseClient):
        self.client = client

    def create_event(self, payload: Dict[str, Any], *, access_token: str) -> Any:
        return self.client.table_insert("client_events", payload, jwt=access_token)

