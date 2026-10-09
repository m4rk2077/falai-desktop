"""Repository for user/device settings synchronization."""
from __future__ import annotations

from typing import Dict, Any

from src.backend.supabase_client import SupabaseClient


class SettingsRepo:
    def __init__(self, client: SupabaseClient):
        self.client = client

    def upsert_user_settings(self, payload: Dict[str, Any], access_token: str):
        return self.client.table_upsert(
            "user_settings",
            payload=payload,
            on_conflict="user_id",
            jwt=access_token,
        )

    def upsert_device_settings(self, payload: Dict[str, Any], access_token: str):
        return self.client.table_upsert(
            "device_settings",
            payload=payload,
            on_conflict="device_id",
            jwt=access_token,
        )

    def get_user_settings(self, user_id: str, access_token: str):
        rows = self.client.table_select(
            "user_settings",
            select="*",
            filters={"user_id": f"eq.{user_id}"},
            jwt=access_token,
        )
        return rows[0] if rows else None
