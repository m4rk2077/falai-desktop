import numpy as np
import pytest

from src.audio.transcriber_groq import GroqTranscriber


class AuthenticationError(Exception):
    status_code = 401


class FailingTranscriptions:
    def create(self, **_kwargs):
        raise AuthenticationError("invalid_api_key")


def test_groq_auth_error_has_safe_actionable_message():
    transcriber = GroqTranscriber(api_key="test-key")
    transcriber.client.audio.transcriptions = FailingTranscriptions()

    with pytest.raises(RuntimeError, match="Chave Groq inválida"):
        transcriber.transcribe(np.array([1, 2], dtype=np.int16))
