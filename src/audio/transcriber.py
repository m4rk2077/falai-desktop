"""
Transcriber module - Integrates with OpenAI Whisper API for speech-to-text
"""
import os
import io
import wave
import numpy as np
from openai import OpenAI
from typing import Optional

from src.utils.logger import get_logger

logger = get_logger(__name__)


class Transcriber:
    """Handles audio transcription using OpenAI Whisper API"""
    
    def __init__(self, api_key: Optional[str] = None, language: str = "pt"):
        """
        Initialize the transcriber
        
        Args:
            api_key: OpenAI API key (if None, reads from environment)
            language: Language code for transcription (pt, en, es, etc.)
        """
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.language = language
        
        if not self.api_key:
            raise ValueError("OpenAI API key is required. Set OPENAI_API_KEY environment variable.")
        
        self.client = OpenAI(api_key=self.api_key)
    
    def _numpy_to_wav_bytes(self, audio_data: np.ndarray, sample_rate: int = 16000) -> bytes:
        """
        Convert numpy array to WAV format bytes
        
        Args:
            audio_data: Audio data as numpy array
            sample_rate: Sample rate in Hz
            
        Returns:
            WAV file as bytes
        """
        # Ensure audio is in the right format
        if audio_data.dtype != np.int16:
            # Convert float32 to int16
            audio_data = (audio_data * 32767).astype(np.int16)
        
        # Create WAV file in memory
        wav_buffer = io.BytesIO()
        
        with wave.open(wav_buffer, 'wb') as wav_file:
            wav_file.setnchannels(1)  # Mono
            wav_file.setsampwidth(2)  # 2 bytes = 16 bit
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(audio_data.tobytes())
        
        wav_buffer.seek(0)
        return wav_buffer.read()
    
    def transcribe(self, audio_data: np.ndarray, sample_rate: int = 16000) -> str:
        """
        Transcribe audio data to text using Whisper API
        
        Args:
            audio_data: Audio data as numpy array
            sample_rate: Sample rate in Hz
            
        Returns:
            Transcribed text
        """
        if len(audio_data) == 0:
            return ""
        
        try:
            # Convert to WAV bytes
            wav_bytes = self._numpy_to_wav_bytes(audio_data, sample_rate)
            
            # Create file-like object for API
            audio_file = io.BytesIO(wav_bytes)
            audio_file.name = "audio.wav"
            
            # Call Whisper API
            logger.info("Sending audio to Whisper API")
            
            response = self.client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                language=self.language,
                response_format="text"
            )
            
            transcription = response.strip()
            logger.info("Transcription received")
            logger.debug("Transcription preview: %s...", transcription[:50])
            
            return transcription
            
        except Exception as e:
            logger.error("Error transcribing audio", exc_info=True)
            raise
    
    def transcribe_file(self, file_path: str) -> str:
        """
        Transcribe audio from a file
        
        Args:
            file_path: Path to audio file
            
        Returns:
            Transcribed text
        """
        try:
            with open(file_path, "rb") as audio_file:
                response = self.client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    language=self.language,
                    response_format="text"
                )
            
            return response.strip()
            
        except Exception as e:
            logger.error("Error transcribing file", exc_info=True)
            raise
