"""Repository for support ticket operations."""
from __future__ import annotations

from typing import Dict, Any, List

from src.backend.supabase_client import SupabaseClient


class SupportRepo:
    def __init__(self, client: SupabaseClient):
        self.client = client

    def create_ticket(self, payload: Dict[str, Any], access_token: str):
        return self.client.table_insert("support_tickets", payload, jwt=access_token)

    def list_tickets(self, user_id: str, access_token: str) -> List[Dict[str, Any]]:
        return self.client.table_select(
            "support_tickets",
            select="*",
            filters={"user_id": f"eq.{user_id}", "order": "created_at.desc"},
            jwt=access_token,
        )
