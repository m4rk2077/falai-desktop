"""
Groq Transcriber module - Integrates with Groq API for ultra-fast speech-to-text
"""
import os
import time
import io
import wave
import numpy as np
from groq import Groq
from typing import Optional

from src.audio.wav_utils import trim_silence
from src.utils.dictation_memory import build_stt_prompt
from src.utils.logger import get_logger

logger = get_logger(__name__)


class GroqTranscriber:
    """Handles audio transcription using Groq API (Whisper)"""
    
    def __init__(self, api_key: Optional[str] = None, language: str = "pt", model: str = "whisper-large-v3-turbo", vocabulary: str = ""):
        """
        Initialize the Groq transcriber
        
        Args:
            api_key: Groq API key (if None, reads from environment)
            language: Language code for transcription (pt, en, es, etc.)
            model: Groq Whisper model name
        """
        self.api_key = api_key or os.getenv("GROQ_API_KEY")
        self.language = language
        self.model = model
        self.vocabulary = vocabulary
        
        if not self.api_key:
            raise ValueError("Groq API key is required. Set GROQ_API_KEY environment variable.")
        
        self.client = Groq(api_key=self.api_key)
    
    def warm_up(self) -> None:
        """Open the HTTPS connection ahead of time (free endpoint) so the real call skips the handshake."""
        now = time.monotonic()
        if now - getattr(self, "_warmed_at", -1e9) < 3:
            return
        self._warmed_at = now
        try:
            self.client.models.list()
        except Exception:
            logger.debug("Groq warm-up failed", exc_info=True)

    def _numpy_to_wav_bytes(self, audio_data: np.ndarray, sample_rate: int = 16000) -> bytes:
        """
        Convert numpy array to WAV format bytes
        """
        # Ensure audio is in the right format
        if audio_data.dtype != np.int16:
            # Convert float32 to int16
            audio_data = (np.clip(audio_data, -1.0, 1.0) * 32767).astype(np.int16)
        
        # Create WAV file in memory
        wav_buffer = io.BytesIO()
        
        with wave.open(wav_buffer, 'wb') as wav_file:
            wav_file.setnchannels(1)  # Mono
            wav_file.setsampwidth(2)  # 2 bytes = 16 bit
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(audio_data.tobytes())
        
        wav_buffer.seek(0)
        return wav_buffer.read()
    
    def transcribe(self, audio_data: np.ndarray, sample_rate: int = 16000, context: str = "") -> str:
        """
        Transcribe audio data to text using Groq API.

        context: tail of the previous dictations, sent with the vocabulary as
        Whisper's prompt so spelling/topic carry over between dictations.
        """
        if len(audio_data) == 0:
            return ""

        try:
            audio_data = trim_silence(audio_data, sample_rate)
            # Convert to WAV bytes
            wav_bytes = self._numpy_to_wav_bytes(audio_data, sample_rate)
            
            # Call Groq API
            logger.info("Sending audio to Groq API (%s)", self.model)
            
            # Groq expects (filename, bytes) tuple for file-like objects in-memory
            transcription = self.client.audio.transcriptions.create(
                file=("audio.wav", wav_bytes),
                model=self.model,
                language=self.language,
                prompt=build_stt_prompt(self.vocabulary, context),
                response_format="text"
            )
            
            # Ensure we get a string back (Groq might return an object depending on version)
            # But response_format="text" usually returns string directly
            result = str(transcription).strip()
            
            logger.info("Groq transcription received")
            logger.debug("Groq transcription preview: %s...", result[:50])
            return result
            
        except Exception as e:
            logger.error("Error transcribing with Groq: %s", type(e).__name__, exc_info=True)
            if getattr(e, "status_code", None) == 401 or type(e).__name__ == "AuthenticationError":
                raise RuntimeError(
                    "Chave Groq inválida. Atualize GROQ_API_KEY no .env e reinicie o FALAI."
                ) from e
            raise
