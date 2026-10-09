from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np

from src.audio.recorder import AudioRecorder
from src.audio.transcriber_groq import GroqTranscriber
from src.utils.groq_corrector import GroqCorrector
from src.utils.message_formatter import format_message_blocks


def test_capture_reuses_device_without_recording_while_prepared(monkeypatch):
    stream = Mock()
    factory = Mock(return_value=stream)
    monkeypatch.setattr('src.audio.recorder.sd.InputStream', factory)
    recorder = AudioRecorder()
    recorder.prepare()
    stream.start.assert_not_called()
    for _ in range(2):
        recorder.start_recording()
        recorder._audio_callback(np.ones((160, 1), dtype=np.float32), 160, None, None)
        assert len(recorder.stop_recording()) == 160
    factory.assert_called_once()
    stream.close.assert_not_called()
    recorder.close()
    stream.close.assert_called_once()


def test_capture_failure_releases_device(monkeypatch):
    stream = Mock()
    stream.start.side_effect = RuntimeError('device removed')
    monkeypatch.setattr('src.audio.recorder.sd.InputStream', Mock(return_value=stream))
    recorder = AudioRecorder()
    import pytest
    with pytest.raises(RuntimeError):
        recorder.start_recording()
    assert not recorder.is_recording
    assert recorder.stream is None
    stream.close.assert_called_once()


def test_formatter_preserves_words_and_splits_complete_sentences():
    text = 'Confere os leads e me manda o resultado. Depois a gente vê o orçamento. Não altera os valores agora. Me avisa quando terminar.'
    result = format_message_blocks(text, audio_data=np.zeros(16000))
    assert result.split() == text.split()
    assert '\n\n' in result
    assert all(block.endswith('.') for block in result.split('\n\n'))


def test_formatter_never_cuts_a_sentence_every_ten_words():
    text = ' '.join(['palavra'] * 60)
    assert format_message_blocks(text) == text


def test_stt_sends_vocabulary(monkeypatch):
    transcriber = GroqTranscriber(api_key='test', vocabulary='Groq, Codex, briefing')
    create = Mock(return_value='Groq e Codex')
    monkeypatch.setattr(transcriber.client.audio.transcriptions, 'create', create)
    assert transcriber.transcribe(np.zeros(160, dtype=np.int16)) == 'Groq e Codex'
    assert create.call_args.kwargs['prompt'] == 'Groq, Codex, briefing'


def test_corrector_rejects_truncation_and_changed_amounts(monkeypatch):
    corrector = GroqCorrector('test')
    original = 'O orçamento é 500 reais, não 5000.'
    for reason, content in [('length', 'O orçamento'), ('stop', 'O orçamento é 5000 reais, não 500.')]:
        create = Mock(return_value=SimpleNamespace(choices=[SimpleNamespace(
            finish_reason=reason, message=SimpleNamespace(content=content))]))
        monkeypatch.setattr(corrector.client.chat.completions, 'create', create)
        assert corrector.correct(original, 'casual') == original


def test_corrector_long_output_budget_and_paragraphs(monkeypatch):
    corrector = GroqCorrector('test')
    original = ('Confere a campanha e me avisa. ' * 100).strip()
    create = Mock(return_value=SimpleNamespace(choices=[SimpleNamespace(
        finish_reason='stop', message=SimpleNamespace(content=original))]))
    monkeypatch.setattr(corrector.client.chat.completions, 'create', create)
    assert corrector.correct(original, 'casual', format_mode='message') == original
    assert create.call_args.kwargs['max_tokens'] > 420


def test_local_startup_uses_source_and_utf8_not_old_install(tmp_path, monkeypatch):
    from src.utils import startup
    root = tmp_path / 'Área'
    root.mkdir()
    (root / 'main.py').touch()
    interpreter = root / 'python.exe'
    interpreter.touch()
    (root / 'pythonw.exe').touch()
    monkeypatch.setattr(startup, '_startup_dir', lambda: tmp_path / 'Startup')
    monkeypatch.setattr(startup.sys, 'frozen', False, raising=False)
    monkeypatch.setattr(startup, '_installed_executable', Mock(side_effect=AssertionError('old build selected')))
    startup.enable_startup(root, interpreter)
    content = startup._startup_file().read_text(encoding='utf-8')
    assert 'chcp 65001' in content
    assert 'pythonw.exe' in content
    assert str(root / 'main.py') in content
