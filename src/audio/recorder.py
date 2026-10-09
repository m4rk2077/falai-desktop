"""
Audio recorder module - Captures audio from microphone in real-time
"""
import sounddevice as sd
import numpy as np
import queue
import threading
from typing import Callable, Optional

from src.utils.logger import get_logger

logger = get_logger(__name__)


class AudioRecorder:
    """Handles real-time audio recording from microphone"""
    
    def __init__(self, sample_rate: int = 16000, channels: int = 1):
        """
        Initialize the audio recorder

        Args:
            sample_rate: Audio sample rate in Hz (Whisper works best with 16kHz)
            channels: Number of audio channels (1 for mono, 2 for stereo)
        """
        self.sample_rate = sample_rate
        self.channels = channels
        self.audio_queue = queue.Queue()
        self.is_recording = False
        self.stream = None
        self.recording_thread = None
        self.last_level = 0.0
        self._streaming_uploader = None  # Set externally for streaming mode
        
    def _audio_callback(self, indata, frames, time, status):
        """Callback function called by sounddevice for each audio block"""
        if status:
            logger.warning("Audio status: %s", status)
        
        # Add audio data to queue
        self.audio_queue.put(indata.copy())

        # Feed streaming uploader if active (sends chunks during recording)
        if self._streaming_uploader:
            try:
                self._streaming_uploader.feed_audio(indata)
            except Exception:
                pass  # Never block audio callback

        # Atualiza nivel de audio (RMS) para waveform em tempo real
        try:
            if indata.size:
                rms = float(np.sqrt(np.mean(indata ** 2)))
                # Escala leve para ficar visualmente responsivo
                self.last_level = max(0.0, min(1.0, rms * 2.0))
        except Exception:
            self.last_level = 0.0
    
    def start_recording(self):
        """Start recording audio from microphone"""
        if self.is_recording:
            logger.warning("Already recording")
            return
        
        self.is_recording = True
        self.audio_queue = queue.Queue()  # Clear queue
        
        try:
            # Start audio stream
            self.prepare()
            self.stream.start()
            logger.info("Recording started (Sample rate: %s Hz)", self.sample_rate)
            
        except Exception as e:
            logger.error("Error starting recording", exc_info=True)
            self.is_recording = False
            self.close()
            raise

    def prepare(self):
        """Open the device without recording; reuse it between dictations."""
        if self.stream is None:
            self.stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                callback=self._audio_callback,
                dtype=np.float32,
            )

    def close(self):
        if self.stream is not None:
            self.stream.close()
            self.stream = None
        self.is_recording = False
    
    def stop_recording(self) -> np.ndarray:
        """
        Stop recording and return all recorded audio
        
        Returns:
            numpy array with recorded audio data
        """
        if not self.is_recording:
            logger.warning("Not recording")
            return np.array([])
        
        self.is_recording = False
        self.last_level = 0.0
        
        # Stop stream
        if self.stream:
            self.stream.stop()
        
        # Collect all audio chunks from queue
        audio_chunks = []
        while not self.audio_queue.empty():
            audio_chunks.append(self.audio_queue.get())
        
        if audio_chunks:
            # Concatenate all chunks
            audio_data = np.concatenate(audio_chunks, axis=0)
            logger.info("Recording stopped (%.2f seconds)", len(audio_data) / self.sample_rate)
            return audio_data
        else:
            logger.warning("No audio data recorded")
            return np.array([])
    
    def get_available_devices(self):
        """Get list of available audio input devices"""
        devices = sd.query_devices()
        input_devices = []
        
        for i, device in enumerate(devices):
            if device['max_input_channels'] > 0:
                input_devices.append({
                    'index': i,
                    'name': device['name'],
                    'channels': device['max_input_channels']
                })
        
        return input_devices
    
    def is_microphone_available(self) -> bool:
        """Check if microphone is available"""
        try:
            devices = self.get_available_devices()
            return len(devices) > 0
        except Exception as e:
            logger.error("Error checking microphone", exc_info=True)
            return False

    def get_level(self) -> float:
        """Retorna o nivel de audio mais recente (0-1)"""
        return float(self.last_level or 0.0)
