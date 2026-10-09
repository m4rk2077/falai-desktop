"""Entitlement service for gating paid features."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from src.backend.supabase_client import SupabaseClient


@dataclass
class Entitlement:
    can_transcribe: bool
    can_correct: bool
    daily_minutes_limit: Optional[int]
    monthly_minutes_limit: Optional[int]
    source: str = "plan"


class EntitlementService:
    def __init__(self, client: SupabaseClient, cache_ttl_seconds: int = 60):
        self.client = client
        self.cache_ttl_seconds = cache_ttl_seconds
        self._cached: Optional[Entitlement] = None
        self._cached_until: float = 0.0

    def get(self, user_id: str, access_token: str, force_refresh: bool = False) -> Entitlement:
        now = time.time()
        if not force_refresh and self._cached and now < self._cached_until:
            return self._cached

        rows = self.client.table_select(
            "user_entitlements",
            select="user_id,can_transcribe,can_correct,daily_minutes_limit,monthly_minutes_limit,source",
            filters={"user_id": f"eq.{user_id}"},
            jwt=access_token,
        )

        if not rows:
            ent = Entitlement(
                can_transcribe=False,
                can_correct=False,
                daily_minutes_limit=0,
                monthly_minutes_limit=0,
                source="none",
            )
        else:
            row = rows[0]
            ent = Entitlement(
                can_transcribe=bool(row.get("can_transcribe", False)),
                can_correct=bool(row.get("can_correct", False)),
                daily_minutes_limit=row.get("daily_minutes_limit"),
                monthly_minutes_limit=row.get("monthly_minutes_limit"),
                source=row.get("source", "plan"),
            )

        self._cached = ent
        self._cached_until = now + self.cache_ttl_seconds
        return ent

    def can_transcribe(self, user_id: str, access_token: str) -> bool:
        return self.get(user_id=user_id, access_token=access_token).can_transcribe
