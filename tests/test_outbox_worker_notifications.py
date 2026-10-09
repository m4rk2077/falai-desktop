from __future__ import annotations

from dataclasses import dataclass

from src.backend.edge_transcribe_service import EdgeTranscribeResult
from src.backend.outbox_worker import OutboxWorker
from src.backend.supabase_client import SupabaseError


class _FakeOutbox:
    def __init__(self, wav_bytes: bytes):
        self._wav_bytes = wav_bytes
        self.synced_ids = []
        self.attempts = []
        self.postprocess_payloads = []

    def get_audio_bytes(self, item_id: str):
        return self._wav_bytes

    def mark_attempt(self, item_id: str, *, error: str, next_attempt_at: float, keep_pending: bool = True):
        self.attempts.append((item_id, error, keep_pending))

    def mark_synced(self, item_id: str):
        self.synced_ids.append(item_id)

    def add_edge_postprocess(self, payload):
        self.postprocess_payloads.append(payload)
        return "pp-1"


class _FakeSession:
    def ensure_fresh_access_token(self, *, min_ttl_seconds: int = 60):
        return "token"

    def force_refresh_access_token(self, *, ignore_ttl: bool = False):
        return "token-refreshed"


class _FakeEdgeTranscriber:
    def __init__(self):
        self.calls = []

    def transcribe_wav_bytes(self, *args, **kwargs):
        self.calls.append(kwargs.get("access_token"))
        return EdgeTranscribeResult(
            transcription={
                "id": "t1",
                "original_text": "olá",
                "corrected_text": "",
                "correction_pending": False,
                "audio_duration_seconds": 1.2,
            },
            usage={"daily_used_seconds": 1.2},
            processing={"tier": "pro"},
        )


class _FakeClientEvents:
    def __init__(self):
        self.calls = []

    def create_event(self, payload, access_token: str):
        self.calls.append(access_token)
        return None


def _build_worker(
    outbox: _FakeOutbox,
    notifications: list[tuple[str, str]],
    *,
    session=None,
    edge_transcriber=None,
    client_events=None,
) -> OutboxWorker:
    return OutboxWorker(
        outbox=outbox,
        session=session or _FakeSession(),
        edge_transcriber=edge_transcriber or _FakeEdgeTranscriber(),
        client_events=client_events or _FakeClientEvents(),
        get_device_id=lambda: "d1",
        get_app_version=lambda: "1.5.0",
        history_add=lambda **kwargs: None,
        history_update_corrected=None,
        notify=lambda t, m: notifications.append((str(t), str(m))),
        record_event=None,
        usage_callback=None,
        poll_seconds=20,
    )


def test_outbox_worker_silences_completion_notification_for_timeout_queue():
    notifications: list[tuple[str, str]] = []
    outbox = _FakeOutbox(b"RIFF" * 64)
    worker = _build_worker(outbox, notifications)
    item = {
        "id": "i-timeout",
        "type": "edge_transcribe",
        "payload": {
            "language": "pt",
            "model": "whisper-large-v3-turbo",
            "queued_reason": "timeout",
        },
        "attempts": 0,
    }

    worker._process_edge_transcribe("i-timeout", item, 0)

    assert outbox.synced_ids == ["i-timeout"]
    assert notifications == []


def test_outbox_worker_notifies_completion_for_network_queue():
    notifications: list[tuple[str, str]] = []
    outbox = _FakeOutbox(b"RIFF" * 64)
    worker = _build_worker(outbox, notifications)
    item = {
        "id": "i-network",
        "type": "edge_transcribe",
        "payload": {
            "language": "pt",
            "model": "whisper-large-v3-turbo",
            "queued_reason": "network",
        },
        "attempts": 0,
    }

    worker._process_edge_transcribe("i-network", item, 0)

    assert outbox.synced_ids == ["i-network"]
    assert len(notifications) == 1
    assert notifications[0][0] == "Transcricao pronta"


class _ClientEvents401ThenOk(_FakeClientEvents):
    def create_event(self, payload, access_token: str):
        self.calls.append(access_token)
        if len(self.calls) == 1:
            raise SupabaseError("401", status_code=401, payload={"message": "invalid jwt"})
        return None


class _Edge401AfterRefresh(_FakeEdgeTranscriber):
    def transcribe_wav_bytes(self, *args, **kwargs):
        self.calls.append(kwargs.get("access_token"))
        raise SupabaseError("401", status_code=401, payload={"message": "invalid jwt"})


def test_outbox_worker_client_event_refreshes_before_notifying_login():
    notifications: list[tuple[str, str]] = []
    outbox = _FakeOutbox(b"")
    client_events = _ClientEvents401ThenOk()
    worker = _build_worker(outbox, notifications, client_events=client_events)
    item = {
        "id": "evt-1",
        "type": "client_event",
        "payload": {"event_type": "ping"},
        "attempts": 0,
    }

    worker._process_client_event("evt-1", item, 0)

    assert outbox.synced_ids == ["evt-1"]
    assert outbox.attempts == []
    assert notifications == []
    assert client_events.calls == ["token", "token-refreshed"]


def test_outbox_worker_silences_false_session_expired_after_refresh_401():
    notifications: list[tuple[str, str]] = []
    outbox = _FakeOutbox(b"RIFF" * 64)
    edge_transcriber = _Edge401AfterRefresh()
    worker = _build_worker(outbox, notifications, edge_transcriber=edge_transcriber)
    item = {
        "id": "i-401",
        "type": "edge_transcribe",
        "payload": {
            "language": "pt",
            "model": "whisper-large-v3-turbo",
            "queued_reason": "server_auth_transient",
        },
        "attempts": 1,
    }

    worker._process_edge_transcribe("i-401", item, 1)

    assert outbox.synced_ids == []
    assert outbox.attempts[-1][0] == "i-401"
    assert outbox.attempts[-1][1] == "401_transient"
    assert notifications == []
    assert edge_transcriber.calls == ["token", "token-refreshed"]
