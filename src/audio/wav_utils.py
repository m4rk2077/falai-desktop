"""Audio helpers used by both local and backend transcription paths."""

from __future__ import annotations

import io
import wave
from typing import Optional

import numpy as np


def numpy_to_pcm16_mono(audio_data: np.ndarray) -> np.ndarray:
    """Convert arbitrary numpy audio into mono int16 PCM samples."""
    if audio_data is None or len(audio_data) == 0:
        return np.array([], dtype=np.int16)

    data = audio_data

    # Downmix to mono if needed.
    if hasattr(data, "ndim") and data.ndim > 1:
        data = data.mean(axis=1)

    # Convert float -> int16 PCM.
    if data.dtype != np.int16:
        data = (data * 32767).astype(np.int16)

    return data


def numpy_to_wav_bytes(audio_data: np.ndarray, sample_rate: int = 16000) -> bytes:
    """Encode numpy audio to a PCM 16-bit mono WAV byte string."""
    pcm16 = numpy_to_pcm16_mono(audio_data)
    if pcm16.size == 0:
        return b""

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(int(sample_rate))
        wav_file.writeframes(pcm16.tobytes())
    return buf.getvalue()



def trim_silence(
    audio_data: np.ndarray,
    sample_rate: int = 16000,
    threshold: float = 0.01,
    pad_seconds: float = 0.25,
    frame_seconds: float = 0.02,
) -> np.ndarray:
    """Drop leading/trailing silence (keeps a small pad around speech).

    Long silent edges are where Whisper tends to hallucinate filler phrases.
    Returns the input unchanged when no frame crosses the threshold.
    """
    if audio_data is None or len(audio_data) == 0:
        return audio_data
    mono = audio_data.mean(axis=1) if getattr(audio_data, "ndim", 1) > 1 else audio_data
    level = np.abs(mono.astype(np.float32))
    if audio_data.dtype == np.int16:
        level /= 32768.0
    frame = max(1, int(sample_rate * frame_seconds))
    n_frames = len(level) // frame
    if n_frames == 0:
        return audio_data
    rms = np.sqrt(np.mean(level[: n_frames * frame].reshape(n_frames, frame) ** 2, axis=1))
    active = np.flatnonzero(rms > threshold)
    if active.size == 0:
        return audio_data
    pad = int(sample_rate * pad_seconds)
    start = max(0, active[0] * frame - pad)
    end = min(len(audio_data), (active[-1] + 1) * frame + pad)
    return audio_data[start:end]
