"""
Dictation memory - short-term context and user replacement rules.

Whisper transcribes each clip in isolation. Feeding the tail of the previous
dictations through the `prompt` parameter keeps names, spelling and topic
consistent across consecutive dictations. Replacement rules fix recurring,
deterministic mistakes (e.g. "fala i" -> "FALAI") without an LLM round-trip.
"""
from __future__ import annotations

import re
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from src.utils.app_paths import ensure_app_data_dir
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Whisper only looks at the last ~224 prompt tokens; keep both parts bounded so
# the vocabulary is never pushed out by the context.
VOCAB_MAX_CHARS = 400
CONTEXT_MAX_CHARS = 350
CONTEXT_MAX_AGE_SECONDS = 15 * 60
CONTEXT_MAX_ITEMS = 3

REPLACEMENTS_FILENAME = "replacements.txt"
_REPLACEMENTS_TEMPLATE = """# FALAI - substituições automáticas aplicadas logo após a transcrição.
# Uma regra por linha:  texto errado => texto certo
# Não diferencia maiúsculas/minúsculas e só troca palavras inteiras.
# Avançado: "re: <regex> => certo" usa expressão regular.
# Linhas começando com # são ignoradas. Ex.:
# fala i => FALAI
# super base => Supabase
"""


def _tail_words(text: str, max_chars: int) -> str:
    """Return the end of `text` within max_chars, cut at a word boundary."""
    text = " ".join(str(text or "").split())
    if len(text) <= max_chars:
        return text
    tail = text[-max_chars:]
    space = tail.find(" ")
    return tail[space + 1:] if 0 <= space < len(tail) - 1 else tail


def build_stt_prompt(vocabulary: str = "", context: str = "") -> Optional[str]:
    """Vocabulary first (bounded), recent dictation last (closest to the audio)."""
    vocab = " ".join(str(vocabulary or "").split())[:VOCAB_MAX_CHARS].strip()
    ctx = _tail_words(context, CONTEXT_MAX_CHARS)
    parts = [p for p in (vocab, ctx) if p]
    return "\n".join(parts) if parts else None


class DictationMemory:
    """Keeps the last few dictations of the current working session."""

    def __init__(self, max_items: int = CONTEXT_MAX_ITEMS, max_age_seconds: float = CONTEXT_MAX_AGE_SECONDS):
        self._items: deque = deque(maxlen=max_items)
        self._max_age = float(max_age_seconds)
        self._lock = threading.Lock()

    def remember(self, text: str, at: Optional[float] = None) -> None:
        text = " ".join(str(text or "").split())
        if len(text) < 2:
            return
        with self._lock:
            self._items.append((at if at is not None else time.time(), text))

    def seed_from_history(self, entries: Iterable[dict]) -> None:
        """Warm up from persisted history so context survives an app restart."""
        for entry in list(entries)[-CONTEXT_MAX_ITEMS:]:
            try:
                ts = datetime.fromisoformat(str(entry.get("timestamp"))).timestamp()
            except Exception:
                continue
            self.remember(entry.get("corrected") or entry.get("original") or "", at=ts)

    def context(self, now: Optional[float] = None) -> str:
        now = now if now is not None else time.time()
        with self._lock:
            recent = [text for ts, text in self._items if now - ts <= self._max_age]
        return _tail_words(" ".join(recent), CONTEXT_MAX_CHARS)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


def parse_replacements(lines: Iterable[str]) -> list[tuple[re.Pattern, str]]:
    rules: list[tuple[re.Pattern, str]] = []
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=>" not in line:
            continue
        wrong, right = (part.strip() for part in line.split("=>", 1))
        if not wrong:
            continue
        if wrong.startswith("re:"):
            # Advanced: raw regex, e.g. "re: agen\w*\s*hub => AgencyHub" (whole-word boundaries added).
            try:
                pattern = re.compile(r"(?<!\w)(?:" + wrong[3:].strip() + r")(?!\w)", re.IGNORECASE)
            except re.error:
                logger.warning("Invalid replacement regex ignored: %s", wrong)
                continue
        else:
            pattern = re.compile(r"(?<!\w)" + r"\s+".join(map(re.escape, wrong.split())) + r"(?!\w)", re.IGNORECASE)
        rules.append((pattern, right))
    return rules


def _match_case(found: str, replacement: str) -> str:
    """Keep sentence-start capitalization: "O cloud" -> "O Claude", not "o Claude"."""
    if found[:1].isupper() and replacement[:1].islower():
        return replacement[:1].upper() + replacement[1:]
    return replacement


class TextReplacements:
    """User-editable replacement rules stored in %APPDATA%/FALAI/replacements.txt."""

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path is not None else ensure_app_data_dir() / REPLACEMENTS_FILENAME
        self._rules: list[tuple[re.Pattern, str]] = []
        self._mtime: Optional[float] = None
        self._ensure_template()

    def _ensure_template(self) -> None:
        try:
            if not self.path.exists():
                self.path.write_text(_REPLACEMENTS_TEMPLATE, encoding="utf-8")
        except Exception:
            logger.warning("Could not create replacements file", exc_info=True)

    def _reload_if_changed(self) -> None:
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            self._rules, self._mtime = [], None
            return
        if mtime == self._mtime:
            return
        try:
            self._rules = parse_replacements(self.path.read_text(encoding="utf-8").splitlines())
            self._mtime = mtime
            logger.info("Loaded %s replacement rules", len(self._rules))
        except Exception:
            logger.warning("Could not read replacements file", exc_info=True)

    def apply(self, text: str) -> str:
        if not text:
            return text
        self._reload_if_changed()
        for pattern, right in self._rules:
            text = pattern.sub(lambda m, r=right: _match_case(m.group(0), r), text)
        return text


DEBUG_AUDIO_DIRNAME = "debug_audio"
DEBUG_AUDIO_KEEP = 50


def save_debug_sample(wav_bytes: bytes, raw_text: str, final_text: str,
                      directory: Optional[Path] = None, keep: int = DEBUG_AUDIO_KEEP) -> Optional[Path]:
    """Keep the last `keep` dictations (audio + texts) locally to evaluate accuracy on real speech.

    Opt-in (setting `save_debug_audio`); nothing leaves the machine.
    """
    if not wav_bytes:
        return None
    try:
        folder = Path(directory) if directory is not None else ensure_app_data_dir() / DEBUG_AUDIO_DIRNAME
        folder.mkdir(parents=True, exist_ok=True)
        stem = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        wav_path = folder / f"{stem}.wav"
        wav_path.write_bytes(wav_bytes)
        (folder / f"{stem}.txt").write_text(f"whisper: {raw_text}\nfinal: {final_text}\n", encoding="utf-8")
        for old in sorted(folder.glob("*.wav"))[:-keep]:
            old.unlink(missing_ok=True)
            old.with_suffix(".txt").unlink(missing_ok=True)
        return wav_path
    except Exception:
        logger.warning("Could not save debug audio sample", exc_info=True)
        return None
