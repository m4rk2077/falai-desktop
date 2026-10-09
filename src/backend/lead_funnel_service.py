"""Client wrapper for official lead lifecycle edge functions."""
from __future__ import annotations

from typing import Any, Dict, Optional

from src.backend.supabase_client import SupabaseClient, SupabaseError


class LeadFunnelService:
    def __init__(self, client: SupabaseClient):
        self.client = client

    def record_lifecycle_event(
        self,
        *,
        access_token: str,
        event_name: str,
        transcription_id: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        token = str(access_token or "").strip()
        if not token:
            raise SupabaseError("Sessão ausente (access_token).")

        payload: Dict[str, Any] = {
            "event_name": str(event_name or "").strip(),
        }
        tid = str(transcription_id or "").strip()
        if tid:
            payload["transcription_id"] = tid
        if isinstance(metadata, dict) and metadata:
            payload["metadata"] = metadata

        response = self.client.function_call(
            "lead_lifecycle_event",
            payload,
            jwt=token,
        )
        if not isinstance(response, dict):
            raise SupabaseError("Resposta inesperada do backend de lead lifecycle.")
        return response
