"""Client for Supabase Edge Function `transcribe`.

This keeps provider API keys (Groq) server-side and uses the user's Supabase session JWT.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any, Dict, Optional

from src.backend.supabase_client import SupabaseClient, SupabaseError


@dataclass
class EdgeTranscribeResult:
    transcription: Dict[str, Any]
    usage: Dict[str, Any]
    processing: Dict[str, Any]

    @property
    def text(self) -> str:
        t = self.transcription or {}
        text_to_paste = str(t.get("text_to_paste") or "").strip()
        if text_to_paste:
            return text_to_paste
        # Prefer corrected text when available.
        return str(t.get("corrected_text") or t.get("original_text") or "").strip()

    @property
    def tier(self) -> str:
        p = self.processing or {}
        return str(p.get("tier") or "").strip().lower()

    @property
    def correction_pending(self) -> bool:
        t = self.transcription or {}
        return bool(t.get("correction_pending", False))


class EdgeTranscribeService:
    def __init__(self, client: SupabaseClient):
        self.client = client

    def transcribe_wav_bytes(
        self,
        wav_bytes: bytes,
        *,
        access_token: str,
        language: str = "pt",
        model: str = "whisper-large-v3-turbo",
        correct: bool = False,
        correction_style: str = "neutro",
        format_mode: str = "balanced",
        domain_profile: str = "none",
        corrector_model: Optional[str] = None,
        device_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        request_timeout_seconds: Optional[float] = None,
    ) -> EdgeTranscribeResult:
        if not access_token:
            raise SupabaseError("Sessão ausente (access_token).")
        if not wav_bytes:
            raise SupabaseError("Audio vazio.")

        payload: Dict[str, Any] = {
            "audio_wav_base64": base64.b64encode(wav_bytes).decode("ascii"),
            "language": language,
            "model": model,
            # Keep formatting/domain hints always available on the backend.
            "format_mode": str(format_mode or "balanced"),
            "domain_profile": str(domain_profile or "none"),
        }
        if correct:
            payload["correct"] = True
            payload["correction_style"] = correction_style
            if corrector_model:
                payload["corrector_model"] = corrector_model
        if device_id:
            payload["device_id"] = device_id
        if metadata:
            payload["metadata"] = metadata

        resp = self.client.function_call(
            "transcribe",
            payload,
            jwt=access_token,
            timeout_seconds=request_timeout_seconds,
        )
        if not isinstance(resp, dict):
            raise SupabaseError("Resposta inesperada do backend.")

        transcription = resp.get("transcription") or {}
        usage = resp.get("usage") or {}
        processing = resp.get("processing") or {}
        if not isinstance(transcription, dict) or not isinstance(usage, dict):
            raise SupabaseError("Resposta inválida do backend (campos ausentes).")
        if not isinstance(processing, dict):
            processing = {}
        if not processing:
            processing = {"tier": "trial", "correction_mode": "sync", "latency_ms": {}}
        return EdgeTranscribeResult(transcription=transcription, usage=usage, processing=processing)

    def postprocess_transcription(
        self,
        *,
        access_token: str,
        transcription_id: str,
        style: str = "neutro",
        format_mode: str = "balanced",
        domain_profile: str = "none",
        request_timeout_seconds: Optional[float] = None,
    ) -> Dict[str, Any]:
        if not access_token:
            raise SupabaseError("Sessão ausente (access_token).")
        tid = str(transcription_id or "").strip()
        if not tid:
            raise SupabaseError("transcription_id ausente.")

        payload = {
            "transcription_id": tid,
            "style": str(style or "neutro"),
            "format_mode": str(format_mode or "balanced"),
            "domain_profile": str(domain_profile or "none"),
        }
        resp = self.client.function_call(
            "transcribe_postprocess",
            payload,
            jwt=access_token,
            timeout_seconds=request_timeout_seconds,
        )
        if not isinstance(resp, dict):
            raise SupabaseError("Resposta inesperada do backend (postprocess).")
        return resp
