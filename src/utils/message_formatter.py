"""
Helpers to format long transcriptions as chat-style message blocks.
"""

from __future__ import annotations

import re
from typing import Iterable

import numpy as np


def _normalize_spacing(text: str) -> str:
    return (
        str(text or "")
        .replace("\r\n", "\n")
        .replace("\t", " ")
        .strip()
    )


def _sentence_units(text: str) -> list[str]:
    clean = _normalize_spacing(text)
    if not clean:
        return []

    parts = [part.strip() for part in re.split(r"(?<=[.!?])\s+", clean) if part.strip()]
    if not parts:
        parts = [clean]

    units: list[str] = []
    for part in parts:
        words = part.split()
        if len(words) > 18 and re.search(r"[,;:]", part):
            subparts = [item.strip() for item in re.split(r"(?<=[,;:])\s+", part) if item.strip()]
            units.extend(subparts or [part])
        elif len(words) > 18:
            for start in range(0, len(words), 10):
                units.append(" ".join(words[start:start + 10]).strip())
        else:
            units.append(part)
    return [unit for unit in units if unit]


def _speech_chunk_word_targets(audio_data: np.ndarray | None, sample_rate: int) -> list[int]:
    if audio_data is None or sample_rate <= 0:
        return []

    try:
        mono = np.asarray(audio_data, dtype=np.float32).reshape(-1)
    except Exception:
        return []

    if mono.size < sample_rate // 2:
        return []

    window_samples = max(1, int(sample_rate * 0.12))
    pause_windows_threshold = max(2, int(round(0.45 / 0.12)))

    trimmed = mono[: (mono.size // window_samples) * window_samples]
    if trimmed.size == 0:
        return []

    windows = trimmed.reshape(-1, window_samples)
    rms = np.sqrt(np.mean(np.square(windows), axis=1))
    if rms.size == 0:
        return []

    max_rms = float(np.max(rms))
    if max_rms <= 0:
        return []

    silence_threshold = max(0.008, max_rms * 0.18)
    speaking = rms >= silence_threshold

    chunks: list[int] = []
    current = 0
    silence_run = 0
    for is_speaking in speaking:
        if is_speaking:
            if silence_run >= pause_windows_threshold and current > 0:
                chunks.append(current)
                current = 0
            silence_run = 0
            current += 1
        else:
            silence_run += 1

    if current > 0:
        chunks.append(current)

    if len(chunks) <= 1:
        return []

    total_windows = sum(chunks)
    if total_windows <= 0:
        return []

    # Word targets are relative weights; downstream logic adjusts them to the real text.
    return [max(6, int(round(chunk / total_windows * 36))) for chunk in chunks]


def _find_nearest_boundary(words: list[str], target_index: int, slack: int = 4) -> int:
    if not words:
        return 0
    target_index = max(1, min(len(words) - 1, target_index))
    candidates: list[int] = []
    start = max(1, target_index - slack)
    end = min(len(words) - 1, target_index + slack)
    for idx in range(start, end + 1):
        token = words[idx - 1].rstrip()
        if token.endswith((".", "!", "?", ";", ":")):
            candidates.append(idx)
    if not candidates:
        for idx in range(start, end + 1):
            token = words[idx - 1].rstrip()
            if token.endswith(","):
                candidates.append(idx)
    if not candidates:
        return target_index
    return min(candidates, key=lambda idx: abs(idx - target_index))


def _format_blocks_from_units(units: Iterable[str], target_words: list[int] | None = None) -> str:
    sequence = [unit.strip() for unit in units if unit and unit.strip()]
    if not sequence:
        return ""

    blocks: list[str] = []
    current_units: list[str] = []
    current_words = 0
    target_index = 0
    targets = target_words or []

    for unit in sequence:
        unit_words = len(unit.split())
        target = targets[target_index] if target_index < len(targets) else 14
        limit = max(8, target + 3)
        should_break = bool(current_units) and (
            current_words + unit_words > limit
            or len(current_units) >= 2
            or current_words >= target
        )
        if should_break:
            blocks.append(" ".join(current_units).strip())
            current_units = []
            current_words = 0
            target_index += 1

        current_units.append(unit)
        current_words += unit_words

    if current_units:
        blocks.append(" ".join(current_units).strip())

    return "\n\n".join(block for block in blocks if block).strip()


def _format_blocks_from_pause_targets(text: str, target_words: list[int]) -> str:
    clean = _normalize_spacing(text)
    words = clean.split()
    if len(words) < 8 or len(target_words) <= 1:
        return ""

    blocks: list[str] = []
    cursor = 0
    remaining_blocks = len(target_words)
    total_target = max(1, sum(target_words))

    for current_target in target_words:
        remaining_blocks -= 1
        remaining_words = len(words) - cursor
        if remaining_words <= 0:
            break
        if remaining_blocks == 0:
            blocks.append(" ".join(words[cursor:]).strip())
            break

        desired = max(6, int(round(remaining_words * (current_target / total_target))))
        desired = min(max(6, desired), max(6, remaining_words - (remaining_blocks * 5)))
        cut = _find_nearest_boundary(words[cursor:], desired, slack=4)
        cut = max(5, min(cut, remaining_words - (remaining_blocks * 4)))
        blocks.append(" ".join(words[cursor:cursor + cut]).strip())
        cursor += cut
        total_target -= current_target

    return "\n\n".join(block for block in blocks if block).strip()


def format_message_blocks(text: str, audio_data: np.ndarray | None = None, sample_rate: int = 16000) -> str:
    """
    Convert a long transcription into smaller chat-style blocks.

    When audio is available, silence gaps are used as the primary guide for where
    blocks should break. Text heuristics are used as fallback.
    """
    clean = _normalize_spacing(text)
    if not clean:
        return clean

    # Silence duration alone cannot align words to audio. Keep semantic sentence
    # boundaries instead of cutting arbitrary word positions inferred from pauses.
    blocks = []
    for paragraph in re.split(r"\n\s*\n", clean):
        sentences = re.split(r"(?<=[.!?])\s+", paragraph.strip())
        current = []
        for sentence in sentences:
            if not sentence:
                continue
            # Split long speech only at an explicit discourse boundary.
            units = [sentence]
            if len(sentence.split()) > 55:
                units = re.split(
                    r"(?<=[,;:])\s+(?=(?:[Aa]gora|[Ee]ntão|[Mm]as|[Pp]or exemplo|[Ss]obre|[Aa]lém disso)\b)",
                    sentence,
                )
            for unit in units:
                if current and (len(current) >= 2 or len((' '.join(current) + ' ' + unit).split()) > 45):
                    blocks.append(' '.join(current))
                    current = []
                current.append(unit)
        if current:
            blocks.append(' '.join(current))
    return '\n\n'.join(blocks)
