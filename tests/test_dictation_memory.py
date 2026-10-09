from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np

from src.audio.transcriber_groq import GroqTranscriber
from src.audio.wav_utils import trim_silence
from src.utils.dictation_memory import (
    CONTEXT_MAX_CHARS,
    DictationMemory,
    TextReplacements,
    build_stt_prompt,
)
from src.utils.groq_corrector import GroqCorrector


def test_prompt_keeps_vocabulary_and_puts_context_last():
    prompt = build_stt_prompt('Groq, Supabase', 'falei do deploy ontem')
    assert prompt == 'Groq, Supabase\nfalei do deploy ontem'
    assert build_stt_prompt('', '') is None


def test_prompt_context_is_bounded_and_cut_on_word():
    long_context = ' '.join(['palavra'] * 200)
    ctx = build_stt_prompt('', long_context)
    assert len(ctx) <= CONTEXT_MAX_CHARS
    assert set(ctx.split()) == {'palavra'}


def test_memory_expires_old_dictations():
    memory = DictationMemory(max_age_seconds=60)
    memory.remember('antigo', at=0)
    memory.remember('recente', at=100)
    assert memory.context(now=120) == 'recente'


def test_memory_seeds_from_history():
    memory = DictationMemory(max_age_seconds=10**9)
    memory.seed_from_history([
        {'timestamp': '2026-10-08T20:00:00', 'original': 'cru', 'corrected': 'Corrigido.'},
        {'timestamp': 'invalido', 'original': 'ignorado'},
    ])
    assert memory.context() == 'Corrigido.'


def test_replacements_whole_words_case_insensitive(tmp_path):
    path = tmp_path / 'replacements.txt'
    path.write_text('# comentario\nfala i => FALAI\nsuper base => Supabase\nlinha invalida\n', encoding='utf-8')
    rules = TextReplacements(path)
    assert rules.apply('Abre o Fala  I e o super base') == 'Abre o FALAI e o Supabase'
    assert rules.apply('falaise') == 'falaise'


def test_replacements_creates_template(tmp_path):
    rules = TextReplacements(tmp_path / 'replacements.txt')
    assert (tmp_path / 'replacements.txt').exists()
    assert rules.apply('nada muda') == 'nada muda'


def test_trim_silence_keeps_speech_with_pad():
    sr = 16000
    audio = np.zeros(sr * 3, dtype=np.float32)
    audio[sr:2 * sr] = 0.2
    trimmed = trim_silence(audio, sr, pad_seconds=0.25)
    assert len(trimmed) == int(sr * 1.5)
    silent = np.zeros(sr, dtype=np.float32)
    assert len(trim_silence(silent, sr)) == sr


def test_stt_sends_context_after_vocabulary(monkeypatch):
    transcriber = GroqTranscriber(api_key='test', vocabulary='Groq')
    create = Mock(return_value='ok')
    monkeypatch.setattr(transcriber.client.audio.transcriptions, 'create', create)
    transcriber.transcribe(np.zeros(160, dtype=np.int16), context='frase anterior')
    assert create.call_args.kwargs['prompt'] == 'Groq\nfrase anterior'


def test_corrector_sends_context_as_reference(monkeypatch):
    corrector = GroqCorrector(api_key='test')
    response = SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop', message=SimpleNamespace(content='Oi, tudo bem?'))])
    create = Mock(return_value=response)
    monkeypatch.setattr(corrector.client.chat.completions, 'create', create)
    assert corrector.correct('oi tudo bem', context='falamos do FALAI') == 'Oi, tudo bem?'
    user_msg = create.call_args.kwargs['messages'][1]['content']
    assert 'falamos do FALAI' in user_msg
    assert user_msg.rstrip().endswith('Texto: oi tudo bem')


def test_corrector_replaces_retired_groq_models():
    assert GroqCorrector(api_key='test', model='llama-3.3-70b-versatile').model == 'openai/gpt-oss-120b'
    assert GroqCorrector(api_key='test', model='openai/gpt-oss-120b').model == 'openai/gpt-oss-120b'


def test_corrector_vocabulary_rule_and_no_reasoning_for_qwen(monkeypatch):
    corrector = GroqCorrector(api_key='test', model='qwen/qwen3.8-27b', vocabulary='Gemini, webhook')
    response = SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop', message=SimpleNamespace(content='<think>x</think>O Gemini caiu.'))])
    create = Mock(return_value=response)
    monkeypatch.setattr(corrector.client.chat.completions, 'create', create)
    assert corrector.correct('o zemini caiu') == 'O Gemini caiu.'
    kwargs = create.call_args.kwargs
    assert kwargs['reasoning_effort'] == 'none'
    assert 'VOCABULÁRIO' in kwargs['messages'][0]['content']
    assert 'VOCABULÁRIO: Gemini, webhook' in kwargs['messages'][1]['content']


def test_warm_up_hits_free_endpoint_once_per_burst(monkeypatch):
    transcriber = GroqTranscriber(api_key='test')
    listing = Mock()
    monkeypatch.setattr(transcriber.client.models, 'list', listing)
    transcriber.warm_up()
    transcriber.warm_up()
    listing.assert_called_once()


def test_debug_samples_keep_only_latest(tmp_path):
    from src.utils.dictation_memory import save_debug_sample
    for i in range(4):
        save_debug_sample(b'RIFF' + bytes([i]), f'raw {i}', f'final {i}', directory=tmp_path, keep=2)
    wavs = sorted(tmp_path.glob('*.wav'))
    assert len(wavs) == 2
    assert wavs[-1].with_suffix('.txt').read_text(encoding='utf-8') == 'whisper: raw 3\nfinal: final 3\n'


def test_corrector_timeout_keeps_original(monkeypatch):
    import httpx
    from groq import APITimeoutError
    corrector = GroqCorrector(api_key='test', vocabulary='Oti')
    slow = Mock(side_effect=APITimeoutError(request=httpx.Request('POST', 'https://api.groq.com')))
    monkeypatch.setattr(corrector.client.chat.completions, 'create', slow)
    assert corrector.correct('abre o oti') == 'abre o oti'
    assert 2.5 <= slow.call_args.kwargs['timeout'] < 3


def test_replacements_keep_sentence_start_capital(tmp_path):
    path = tmp_path / 'replacements.txt'
    path.write_text('o cloud => o Claude\n', encoding='utf-8')
    rules = TextReplacements(path)
    assert rules.apply('O cloud fez. Pede pro o cloud.') == 'O Claude fez. Pede pro o Claude.'


def test_regex_replacement_rules(tmp_path):
    path = tmp_path / 'replacements.txt'
    path.write_text(r're: ag[eê]n\w*[\s-]*hub => AgencyHub' + '\n' + 're: ([ => quebrada\n', encoding='utf-8')
    rules = TextReplacements(path)
    assert rules.apply('Abre o AgenC hub e o Agents-Hub e o Agência Hub.') == 'Abre o AgencyHub e o AgencyHub e o AgencyHub.'
    assert rules.apply('o agente do hub') == 'o agente do hub'


def test_corrector_falls_back_when_model_removed(monkeypatch):
    import httpx
    from groq import NotFoundError
    corrector = GroqCorrector(api_key='test', model='qwen/qwen3.8-27b')
    response = SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop', message=SimpleNamespace(content='Oi.'))])
    gone = NotFoundError('model not found', response=httpx.Response(404, request=httpx.Request('POST', 'https://x')), body=None)
    create = Mock(side_effect=[gone, response])
    monkeypatch.setattr(corrector.client.chat.completions, 'create', create)
    assert corrector.correct('oi') == 'Oi.'
    assert corrector.model == 'openai/gpt-oss-120b'
    assert create.call_args.kwargs['model'] == 'openai/gpt-oss-120b'
    assert create.call_args.kwargs['reasoning_effort'] == 'low'


def test_update_repo_is_configurable(monkeypatch):
    import main
    monkeypatch.setenv('FALAI_UPDATE_REPO', 'someone/falai')
    service = main.FalaiApp._update_service()
    assert (service.owner, service.repo) == ('someone', 'falai')
