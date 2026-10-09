"""Background worker that drains the OutboxRepo when possible.

Runs as a daemon thread:
- If offline: keeps items pending and retries with backoff.
  (Does NOT logout the user.)
- If session invalid: notifies the UI and waits for user to login again.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Optional

import requests

from src.backend.client_events_repo import ClientEventsRepo
from src.backend.edge_transcribe_service import EdgeTranscribeService, EdgeTranscribeResult
from src.backend.outbox_repo import OutboxRepo
from src.backend.session_manager import LoginRequiredError, OfflineError, SessionManager
from src.backend.supabase_client import SupabaseError
from src.utils.logger import get_logger

logger = get_logger(__name__)


def _next_utc_midnight_epoch() -> float:
    now = datetime.now(timezone.utc)
    nxt = (now + timedelta(days=1)).replace(hour=0, minute=0, second=5, microsecond=0)
    return float(nxt.timestamp())


def _backoff_seconds(attempts: int) -> float:
    # 15s, 30s, 60s, 120s, ... capped at 30min
    a = max(0, int(attempts))
    return float(min(1800, (2 ** a) * 15))


class OutboxWorker:
    def __init__(
        self,
        *,
        outbox: OutboxRepo,
        session: SessionManager,
        edge_transcriber: EdgeTranscribeService,
        client_events: ClientEventsRepo,
        get_device_id: Callable[[], str],
        get_app_version: Callable[[], str],
        history_add: Callable[..., Any],
        history_update_corrected: Optional[Callable[[str, Optional[str]], bool]] = None,
        notify: Callable[[str, str], Any],
        record_event: Optional[Callable[..., Any]] = None,
        usage_callback: Optional[Callable[[Dict[str, Any]], Any]] = None,
        poll_seconds: int = 20,
    ):
        self.outbox = outbox
        self.session = session
        self.edge_transcriber = edge_transcriber
        self.client_events = client_events
        self.get_device_id = get_device_id
        self.get_app_version = get_app_version
        self.history_add = history_add
        self.history_update_corrected = history_update_corrected
        self.notify = notify
        self.record_event = record_event
        self.usage_callback = usage_callback
        self.poll_seconds = max(5, int(poll_seconds))

        self._stop = False
        self._login_notice_at = 0.0

    def stop(self) -> None:
        self._stop = True

    def run_forever(self) -> None:
        logger.info("OutboxWorker started (poll=%ss)", self.poll_seconds)
        while not self._stop:
            try:
                self.outbox.prune_expired()
                due = self.outbox.list_due(limit=5)
                if not due:
                    time.sleep(self.poll_seconds)
                    continue

                for item in due:
                    if self._stop:
                        break
                    self._process_item(item)
                    # Small yield between items.
                    time.sleep(0.1)

            except Exception:
                logger.warning("OutboxWorker loop error", exc_info=True)
                time.sleep(self.poll_seconds)

        logger.info("OutboxWorker stopped")

    def _notify_login_required_throttled(self) -> None:
        now = time.time()
        if (now - float(self._login_notice_at or 0.0)) < 60:
            return
        self._login_notice_at = now
        try:
            self.notify("Sessao expirada", "Faça login novamente para continuar.")
        except Exception:
            pass

    def _mark_transient_auth_retry(self, item_id: str, attempts: int, *, error: str = "401_transient") -> None:
        self.outbox.mark_attempt(
            item_id,
            error=error,
            next_attempt_at=time.time() + _backoff_seconds(attempts),
            keep_pending=True,
        )

    def _force_refresh_after_401(
        self,
        *,
        item_id: str,
        attempts: int,
        login_error: str,
        offline_error: str,
    ) -> Optional[str]:
        try:
            return self.session.force_refresh_access_token(ignore_ttl=True)
        except LoginRequiredError:
            self._notify_login_required_throttled()
            self.outbox.mark_attempt(
                item_id,
                error=login_error,
                next_attempt_at=time.time() + 600,
                keep_pending=True,
            )
            return None
        except OfflineError:
            self.outbox.mark_attempt(
                item_id,
                error=offline_error,
                next_attempt_at=time.time() + _backoff_seconds(attempts),
                keep_pending=True,
            )
            return None

    def _process_item(self, item: Dict[str, Any]) -> None:
        item_id = str(item.get("id") or "").strip()
        item_type = str(item.get("type") or "").strip()
        attempts = int(item.get("attempts") or 0)

        if not item_id or not item_type:
            return

        if item_type == "client_event":
            self._process_client_event(item_id, item, attempts)
            return

        if item_type == "edge_transcribe":
            self._process_edge_transcribe(item_id, item, attempts)
            return

        if item_type == "edge_postprocess":
            self._process_edge_postprocess(item_id, item, attempts)
            return

    def _process_client_event(self, item_id: str, item: Dict[str, Any], attempts: int) -> None:
        payload = item.get("payload") or {}
        if not isinstance(payload, dict) or not payload:
            self.outbox.mark_synced(item_id)
            return

        try:
            token = self.session.ensure_fresh_access_token(min_ttl_seconds=60)
        except LoginRequiredError:
            self._notify_login_required_throttled()
            self.outbox.mark_attempt(item_id, error="login_required", next_attempt_at=time.time() + 600, keep_pending=True)
            return
        except OfflineError:
            self.outbox.mark_attempt(
                item_id,
                error="offline",
                next_attempt_at=time.time() + _backoff_seconds(attempts),
                keep_pending=True,
            )
            return

        # Fill correlation fields if missing.
        try:
            payload.setdefault("device_id", self.get_device_id() or "")
            payload.setdefault("app_version", self.get_app_version() or "")
        except Exception:
            pass

        try:
            self.client_events.create_event(payload, access_token=token)
            self.outbox.mark_synced(item_id)
        except SupabaseError as exc:
            code = getattr(exc, "status_code", None)
            if code == 401:
                token2 = self._force_refresh_after_401(
                    item_id=item_id,
                    attempts=attempts,
                    login_error="401_login_required",
                    offline_error="offline_refresh",
                )
                if not token2:
                    return
                try:
                    self.client_events.create_event(payload, access_token=token2)
                    self.outbox.mark_synced(item_id)
                    return
                except SupabaseError as exc2:
                    code2 = getattr(exc2, "status_code", None)
                    if code2 == 401:
                        logger.warning(
                            "Client event still returned 401 after refresh; treating as transient backend auth issue"
                        )
                        self._mark_transient_auth_retry(item_id, attempts)
                        return
                    self.outbox.mark_attempt(
                        item_id,
                        error=f"supabase_{code2}",
                        next_attempt_at=time.time() + _backoff_seconds(attempts),
                        keep_pending=True,
                    )
                    return
                except requests.exceptions.RequestException:
                    self.outbox.mark_attempt(
                        item_id,
                        error="offline",
                        next_attempt_at=time.time() + _backoff_seconds(attempts),
                        keep_pending=True,
                    )
                    return
                except Exception:
                    self.outbox.mark_attempt(
                        item_id,
                        error="unexpected",
                        next_attempt_at=time.time() + _backoff_seconds(attempts),
                        keep_pending=True,
                    )
                    return
            # Temporary failures (rate limit/5xx) -> retry.
            self.outbox.mark_attempt(
                item_id,
                error=f"supabase_{code}",
                next_attempt_at=time.time() + _backoff_seconds(attempts),
                keep_pending=True,
            )
        except requests.exceptions.RequestException:
            self.outbox.mark_attempt(
                item_id,
                error="offline",
                next_attempt_at=time.time() + _backoff_seconds(attempts),
                keep_pending=True,
            )
        except Exception:
            self.outbox.mark_attempt(
                item_id,
                error="unexpected",
                next_attempt_at=time.time() + _backoff_seconds(attempts),
                keep_pending=True,
            )

    def _process_edge_transcribe(self, item_id: str, item: Dict[str, Any], attempts: int) -> None:
        payload = item.get("payload") or {}
        if not isinstance(payload, dict):
            payload = {}

        wav_bytes = self.outbox.get_audio_bytes(item_id)
        if not wav_bytes:
            # Missing audio: drop item.
            self.outbox.mark_synced(item_id)
            return

        try:
            token = self.session.ensure_fresh_access_token(min_ttl_seconds=60)
        except LoginRequiredError:
            self._notify_login_required_throttled()
            self.outbox.mark_attempt(item_id, error="login_required", next_attempt_at=time.time() + 600, keep_pending=True)
            return
        except OfflineError:
            self.outbox.mark_attempt(
                item_id,
                error="offline",
                next_attempt_at=time.time() + _backoff_seconds(attempts),
                keep_pending=True,
            )
            return

        # Build Edge Function call params.
        language = str(payload.get("language") or "pt")
        model = str(payload.get("model") or "whisper-large-v3-turbo")
        correct = bool(payload.get("correct", False))
        correction_style = str(payload.get("correction_style") or "neutro")
        format_mode = str(payload.get("format_mode") or "balanced")
        domain_profile = str(payload.get("domain_profile") or "none")
        corrector_model = payload.get("corrector_model", None)
        duration_seconds = payload.get("duration_seconds", None)
        try:
            dur_s = float(duration_seconds) if duration_seconds is not None else (len(wav_bytes) / 32000.0)
        except Exception:
            dur_s = len(wav_bytes) / 32000.0
        request_timeout_seconds = max(45.0, min(240.0, 20.0 + (dur_s * 3.0)))

        device_id = ""
        try:
            device_id = (self.get_device_id() or "").strip()
        except Exception:
            device_id = ""

        def _call(access_token: str) -> EdgeTranscribeResult:
            return self.edge_transcriber.transcribe_wav_bytes(
                wav_bytes,
                access_token=access_token,
                language=language,
                model=model,
                correct=correct,
                correction_style=correction_style,
                format_mode=format_mode,
                domain_profile=domain_profile,
                corrector_model=str(corrector_model) if corrector_model else None,
                device_id=device_id or None,
                metadata={"queued": True},
                request_timeout_seconds=request_timeout_seconds,
            )

        try:
            result = _call(token)
        except SupabaseError as exc:
            code = getattr(exc, "status_code", None)
            if code == 426:
                self.outbox.mark_attempt(
                    item_id,
                    error="upgrade_required",
                    next_attempt_at=time.time() + 999999,
                    keep_pending=False,
                )
                try:
                    self.notify("Atualizacao obrigatoria", "Atualize o app para continuar enviando transcricoes.")
                except Exception:
                    pass
                return
            if code == 401:
                # Try refresh once and retry.
                token2 = self._force_refresh_after_401(
                    item_id=item_id,
                    attempts=attempts,
                    login_error="401_login_required",
                    offline_error="offline_refresh",
                )
                if not token2:
                    return
                try:
                    result = _call(token2)
                except SupabaseError as exc2:
                    code2 = getattr(exc2, "status_code", None)
                    if code2 == 401:
                        logger.warning(
                            "Outbox transcribe still returned 401 after refresh; treating as transient backend auth issue"
                        )
                        self._mark_transient_auth_retry(item_id, attempts)
                        return
                    self.outbox.mark_attempt(
                        item_id,
                        error=f"supabase_{code2}",
                        next_attempt_at=time.time() + _backoff_seconds(attempts),
                        keep_pending=True,
                    )
                    return
                except requests.exceptions.ReadTimeout:
                    self.outbox.mark_attempt(
                        item_id,
                        error="timeout",
                        next_attempt_at=time.time() + _backoff_seconds(attempts),
                        keep_pending=True,
                    )
                    return
                except requests.exceptions.RequestException:
                    self.outbox.mark_attempt(
                        item_id,
                        error="offline",
                        next_attempt_at=time.time() + _backoff_seconds(attempts),
                        keep_pending=True,
                    )
                    return
                except Exception:
                    self.outbox.mark_attempt(
                        item_id,
                        error="unexpected",
                        next_attempt_at=time.time() + _backoff_seconds(attempts),
                        keep_pending=True,
                    )
                    return

            if code == 403 and isinstance(getattr(exc, "payload", None), dict):
                reason = str((exc.payload or {}).get("reason") or "").strip()
                # Daily quota resets at midnight UTC (server uses UTC).
                if reason in ("daily_limit_reached", "daily_remaining_insufficient"):
                    self.outbox.mark_attempt(
                        item_id,
                        error=f"quota_{reason}",
                        next_attempt_at=_next_utc_midnight_epoch(),
                        keep_pending=True,
                    )
                    try:
                        self.notify("Fila offline", "Vamos tentar novamente amanha (limite diario).")
                    except Exception:
                        pass
                    return

                # Permanent blocks should not loop forever.
                self.outbox.mark_attempt(
                    item_id,
                    error=f"blocked_{reason or '403'}",
                    next_attempt_at=time.time() + 999999,
                    keep_pending=False,
                )
                try:
                    self.notify("Fila offline", "Nao foi possivel transcrever (acesso bloqueado).")
                except Exception:
                    pass
                return

            # Other Supabase errors: retry with backoff.
            self.outbox.mark_attempt(
                item_id,
                error=f"supabase_{code}",
                next_attempt_at=time.time() + _backoff_seconds(attempts),
                keep_pending=True,
            )
            return
        except requests.exceptions.ReadTimeout:
            self.outbox.mark_attempt(
                item_id,
                error="timeout",
                next_attempt_at=time.time() + _backoff_seconds(attempts),
                keep_pending=True,
            )
            return
        except requests.exceptions.RequestException:
            self.outbox.mark_attempt(
                item_id,
                error="offline",
                next_attempt_at=time.time() + _backoff_seconds(attempts),
                keep_pending=True,
            )
            return
        except Exception:
            self.outbox.mark_attempt(
                item_id,
                error="unexpected",
                next_attempt_at=time.time() + _backoff_seconds(attempts),
                keep_pending=True,
            )
            return

        # Success: remove from outbox, persist to history, notify.
        try:
            t = result.transcription or {}
            original = str(t.get("original_text") or "").strip()
            corrected = str(t.get("corrected_text") or "").strip() or None
            transcription_id = str(t.get("id") or "").strip()

            dur = t.get("audio_duration_seconds", None)
            if dur is None and duration_seconds is not None:
                dur = duration_seconds
            try:
                dur_f = float(dur) if dur is not None else 0.0
            except Exception:
                dur_f = 0.0

            self.history_add(
                original=original or (corrected or ""),
                corrected=corrected,
                duration_seconds=dur_f,
                transcription_id=transcription_id or None,
            )
        except Exception:
            logger.warning("Failed to write history from outbox item", exc_info=True)

        try:
            if self.usage_callback and isinstance(result.usage, dict) and result.usage:
                self.usage_callback(result.usage)
        except Exception:
            pass

        try:
            t = result.transcription or {}
            tid = str(t.get("id") or "").strip()
            pending = bool(t.get("correction_pending", False))
            if result.tier == "pro" and pending and tid:
                self.outbox.add_edge_postprocess(
                    {
                        "transcription_id": tid,
                        "style": correction_style,
                        "format_mode": format_mode,
                        "domain_profile": domain_profile,
                    }
                )
        except Exception:
            pass

        self.outbox.mark_synced(item_id)
        # Avoid noisy notifications when fallback happened due timeout only.
        reason = str((payload or {}).get("queued_reason") or "").strip().lower()
        should_notify = reason != "timeout"
        if should_notify:
            try:
                self.notify("Transcricao pronta", "Sua transcricao offline ficou pronta e foi salva no historico.")
            except Exception:
                pass

    def _process_edge_postprocess(self, item_id: str, item: Dict[str, Any], attempts: int) -> None:
        payload = item.get("payload") or {}
        if not isinstance(payload, dict):
            payload = {}

        transcription_id = str(payload.get("transcription_id") or "").strip()
        if not transcription_id:
            self.outbox.mark_synced(item_id)
            return

        style = str(payload.get("style") or "neutro")
        format_mode = str(payload.get("format_mode") or "balanced")
        domain_profile = str(payload.get("domain_profile") or "none")

        try:
            token = self.session.ensure_fresh_access_token(min_ttl_seconds=60)
        except LoginRequiredError:
            self._notify_login_required_throttled()
            self.outbox.mark_attempt(item_id, error="login_required", next_attempt_at=time.time() + 600, keep_pending=True)
            return
        except OfflineError:
            self.outbox.mark_attempt(
                item_id,
                error="offline",
                next_attempt_at=time.time() + _backoff_seconds(attempts),
                keep_pending=True,
            )
            return

        try:
            result = self.edge_transcriber.postprocess_transcription(
                access_token=token,
                transcription_id=transcription_id,
                style=style,
                format_mode=format_mode,
                domain_profile=domain_profile,
                request_timeout_seconds=60.0,
            )
        except SupabaseError as exc:
            code = getattr(exc, "status_code", None)
            if code == 426:
                self.outbox.mark_attempt(
                    item_id,
                    error="upgrade_required",
                    next_attempt_at=time.time() + 999999,
                    keep_pending=False,
                )
                try:
                    self.notify("Atualizacao obrigatoria", "Atualize o app para concluir pos-processamento.")
                except Exception:
                    pass
                return
            if code == 401:
                token2 = self._force_refresh_after_401(
                    item_id=item_id,
                    attempts=attempts,
                    login_error="401_login_required",
                    offline_error="offline_refresh",
                )
                if not token2:
                    try:
                        if self.record_event:
                            self.record_event(
                                event_type="postprocess_failed",
                                severity="warning",
                                message="Postprocess 401",
                                details={"transcription_id": transcription_id, "code": 401},
                            )
                    except Exception:
                        pass
                    return
                try:
                    result = self.edge_transcriber.postprocess_transcription(
                        access_token=token2,
                        transcription_id=transcription_id,
                        style=style,
                        format_mode=format_mode,
                        domain_profile=domain_profile,
                        request_timeout_seconds=60.0,
                    )
                except SupabaseError as exc2:
                    code2 = getattr(exc2, "status_code", None)
                    if code2 == 401:
                        logger.warning(
                            "Outbox postprocess still returned 401 after refresh; treating as transient backend auth issue"
                        )
                        self._mark_transient_auth_retry(item_id, attempts)
                        try:
                            if self.record_event:
                                self.record_event(
                                    event_type="postprocess_failed",
                                    severity="warning",
                                    message="Postprocess 401 after refresh",
                                    details={"transcription_id": transcription_id, "code": 401},
                                )
                        except Exception:
                            pass
                        return
                    self.outbox.mark_attempt(
                        item_id,
                        error=f"supabase_{code2}",
                        next_attempt_at=time.time() + _backoff_seconds(attempts),
                        keep_pending=True,
                    )
                    try:
                        if self.record_event:
                            self.record_event(
                                event_type="postprocess_failed",
                                severity="warning",
                                message="Postprocess Supabase error",
                                details={"transcription_id": transcription_id, "code": code2},
                            )
                    except Exception:
                        pass
                    return
                except requests.exceptions.ReadTimeout:
                    self.outbox.mark_attempt(
                        item_id,
                        error="timeout",
                        next_attempt_at=time.time() + _backoff_seconds(attempts),
                        keep_pending=True,
                    )
                    return
                except requests.exceptions.RequestException:
                    self.outbox.mark_attempt(
                        item_id,
                        error="offline",
                        next_attempt_at=time.time() + _backoff_seconds(attempts),
                        keep_pending=True,
                    )
                    return
                except Exception:
                    self.outbox.mark_attempt(
                        item_id,
                        error="unexpected",
                        next_attempt_at=time.time() + _backoff_seconds(attempts),
                        keep_pending=True,
                    )
                    return
            if code == 404:
                # Item no longer exists or not visible to this user; no point retrying.
                self.outbox.mark_synced(item_id)
                return
            self.outbox.mark_attempt(
                item_id,
                error=f"supabase_{code}",
                next_attempt_at=time.time() + _backoff_seconds(attempts),
                keep_pending=True,
            )
            try:
                if self.record_event:
                    self.record_event(
                        event_type="postprocess_failed",
                        severity="warning",
                        message="Postprocess Supabase error",
                        details={"transcription_id": transcription_id, "code": code},
                    )
            except Exception:
                pass
            return
        except requests.exceptions.ReadTimeout:
            self.outbox.mark_attempt(
                item_id,
                error="timeout",
                next_attempt_at=time.time() + _backoff_seconds(attempts),
                keep_pending=True,
            )
            try:
                if self.record_event:
                    self.record_event(
                        event_type="postprocess_failed",
                        severity="warning",
                        message="Postprocess timeout",
                        details={"transcription_id": transcription_id},
                    )
            except Exception:
                pass
            return
        except requests.exceptions.RequestException:
            self.outbox.mark_attempt(
                item_id,
                error="offline",
                next_attempt_at=time.time() + _backoff_seconds(attempts),
                keep_pending=True,
            )
            try:
                if self.record_event:
                    self.record_event(
                        event_type="postprocess_failed",
                        severity="warning",
                        message="Postprocess offline",
                        details={"transcription_id": transcription_id},
                    )
            except Exception:
                pass
            return
        except Exception:
            self.outbox.mark_attempt(
                item_id,
                error="unexpected",
                next_attempt_at=time.time() + _backoff_seconds(attempts),
                keep_pending=True,
            )
            try:
                if self.record_event:
                    self.record_event(
                        event_type="postprocess_failed",
                        severity="warning",
                        message="Postprocess unexpected error",
                        details={"transcription_id": transcription_id},
                    )
            except Exception:
                pass
            return

        corrected = str((result or {}).get("corrected_text") or "").strip()
        try:
            if self.history_update_corrected and corrected:
                self.history_update_corrected(transcription_id, corrected)
        except Exception:
            logger.warning("Failed to update history with postprocess result", exc_info=True)

        self.outbox.mark_synced(item_id)
        try:
            if self.record_event:
                self.record_event(
                    event_type="postprocess_success",
                    severity="info",
                    message="Postprocess completed",
                    details={"transcription_id": transcription_id},
                )
        except Exception:
            pass
        # Intentionally silent: background refinement should not interrupt the user.
