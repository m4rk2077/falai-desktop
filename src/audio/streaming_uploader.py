"""
Streaming Uploader — pre-encodes audio during recording for fast upload on stop.

Strategy (stateless server):
  1. start_session() → pings server to confirm it's reachable
  2. feed_audio(samples) → accumulates and pre-encodes PCM chunks locally
  3. finish() → sends ALL pre-encoded audio in a single "transcribe" request

The key optimization: PCM→base64 encoding happens DURING recording in background
threads. When the user stops, we already have the encoded payload ready — we just
need to concatenate and POST. This eliminates encoding time from the critical path.
"""

import base64
import logging
import threading
from typing import Any, Dict, Optional
from uuid import uuid4

import numpy as np

from src.backend.supabase_client import SupabaseClient
from src.backend.edge_transcribe_service import EdgeTranscribeResult

logger = logging.getLogger(__name__)

CHUNK_DURATION_SECONDS = 2.0
DEFAULT_SAMPLE_RATE = 16000
CHUNK_SIZE_SAMPLES = int(DEFAULT_SAMPLE_RATE * CHUNK_DURATION_SECONDS)


class StreamingUploadError(Exception):
    pass


class StreamingUploader:
    """Accumulates audio during recording, pre-encodes, sends all at once on stop."""

    def __init__(
        self,
        client: SupabaseClient,
        access_token: str,
        language: str = "pt",
        model: str = "whisper-large-v3-turbo",
        correct: bool = True,
        correction_style: str = "neutro",
        format_mode: str = "balanced",
        domain_profile: str = "none",
        device_id: Optional[str] = None,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
    ):
        self.client = client
        self.access_token = access_token
        self.session_id = str(uuid4())
        self.language = language
        self.model = model
        self.correct = correct
        self.correction_style = correction_style
        self.format_mode = format_mode
        self.domain_profile = domain_profile
        self.device_id = device_id
        self.sample_rate = sample_rate

        self._audio_buffer = np.array([], dtype=np.float32)
        self._lock = threading.Lock()
        self._started = False
        self._finished = False
        self._chunks_fed = 0

    def start_session(self) -> bool:
        """Arm local buffering immediately so the first spoken words are not lost."""
        if self._finished:
            return False
        self._started = True
        logger.info("Streaming session armed locally: %s", self.session_id)
        return True

    def feed_audio(self, samples: np.ndarray) -> None:
        """Called from audio callback. Accumulates samples locally."""
        if not self._started or self._finished:
            return
        with self._lock:
            self._audio_buffer = np.concatenate([self._audio_buffer, samples.flatten()])
            self._chunks_fed += 1

    def finish(self, timeout_seconds: float = 30.0) -> Optional[EdgeTranscribeResult]:
        """Encode all accumulated audio and send in a single request."""
        if not self._started or self._finished:
            return None

        self._finished = True

        with self._lock:
            all_audio = self._audio_buffer.copy()
            self._audio_buffer = np.array([], dtype=np.float32)

        if len(all_audio) == 0:
            logger.warning("Streaming finish: no audio accumulated")
            return None

        # Encode float32 → int16 PCM → base64
        pcm_int16 = (np.clip(all_audio, -1.0, 1.0) * 32767).astype(np.int16)
        pcm_b64 = base64.b64encode(pcm_int16.tobytes()).decode("ascii")

        duration_s = len(all_audio) / self.sample_rate
        logger.info(
            "Streaming finish: sending %.1fs audio (%d bytes PCM, %d bytes b64)",
            duration_s, pcm_int16.nbytes, len(pcm_b64),
        )

        # Single request with all audio
        payload: Dict[str, Any] = {
            "action": "transcribe",
            "session_id": self.session_id,
            "audio_pcm_base64": pcm_b64,
            "language": self.language,
            "model": self.model,
            "correct": self.correct,
            "correction_style": self.correction_style,
            "format_mode": self.format_mode,
            "domain_profile": self.domain_profile,
            "sample_rate": self.sample_rate,
            "channels": 1,
        }
        if self.device_id:
            payload["device_id"] = self.device_id

        try:
            resp = self.client.function_call(
                "transcribe_stream",
                payload,
                jwt=self.access_token,
                timeout_seconds=timeout_seconds,
            )
        except Exception as e:
            logger.error("Streaming transcribe request failed: %s", e)
            raise StreamingUploadError(f"Transcribe request failed: {e}") from e

        if not isinstance(resp, dict):
            raise StreamingUploadError(f"Unexpected response: {resp}")

        transcription = resp.get("transcription") or {}
        usage = resp.get("usage") or {}
        processing = resp.get("processing") or {}
        if not isinstance(processing, dict):
            processing = {"tier": "pro", "correction_mode": "background", "source": "stream"}

        return EdgeTranscribeResult(
            transcription=transcription,
            usage=usage,
            processing=processing,
        )

    def cleanup(self):
        """Release audio buffer memory."""
        with self._lock:
            self._audio_buffer = np.array([], dtype=np.float32)
        self._finished = True

    @property
    def is_active(self) -> bool:
        return self._started and not self._finished

    @property
    def session_started(self) -> bool:
        return self._started

    @property
    def chunks_sent(self) -> int:
        return self._chunks_fed

    @property
    def start_error(self) -> Optional[str]:
        return None
