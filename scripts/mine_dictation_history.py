"""
Mine the local (encrypted) dictation history for recurring STT mistakes.

Compares each Whisper output ("original") with the corrected text, word by word,
and counts substitutions the corrector keeps making. Recurring ones are good
candidates for %APPDATA%/FALAI/replacements.txt (deterministic, no LLM).
It also lists frequent proper nouns/terms missing from personal_vocabulary.

Nothing is applied automatically: suggestions are written to
%APPDATA%/FALAI/replacements_suggestions.txt for review.

Usage:  python scripts/mine_dictation_history.py [--min-count 3]
"""
from __future__ import annotations

import argparse
import difflib
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config.settings import Settings  # noqa: E402
from src.utils.app_paths import ensure_app_data_dir  # noqa: E402
from src.utils.history import TranscriptionHistory  # noqa: E402

WORD = re.compile(r"[\w][\w'\-\.]*[\w]|[\w]", re.UNICODE)


HYPHENS = dict.fromkeys(map(ord, "‐‑‒–­"), "-")
SENTENCE_END = re.compile(r"[.!?:\n]\s*$")


def _normalize(text: str) -> str:
    return (text or "").translate(HYPHENS)


def _words(text: str) -> list[str]:
    return WORD.findall(_normalize(text))


def _fold(word: str) -> str:
    """Case/accent-insensitive key: ignores changes that are only capitalization or accents."""
    nfkd = unicodedata.normalize("NFKD", word.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def mine_substitutions(entries) -> Counter:
    pairs: Counter = Counter()
    for entry in entries:
        original, corrected = entry.get("original") or "", entry.get("corrected") or ""
        if not original or not corrected:
            continue
        a, b = _words(original), _words(corrected)
        matcher = difflib.SequenceMatcher(a=[_fold(w) for w in a], b=[_fold(w) for w in b], autojunk=False)
        for op, i1, i2, j1, j2 in matcher.get_opcodes():
            # Short replacements only: long ones are rewrites, not transcription errors.
            if op != "replace" or (i2 - i1) > 3 or (j2 - j1) > 3:
                continue
            wrong, right = " ".join(a[i1:i2]), " ".join(b[j1:j2])
            if _fold(wrong) != _fold(right):
                pairs[(wrong.lower(), right)] += 1
    return pairs


def mine_terms(entries, vocabulary: str) -> Counter:
    """Words written capitalized mid-sentence (names/brands/acronyms) more often than lowercase."""
    known = {_fold(t.strip()) for t in vocabulary.split(",") if t.strip()}
    capitalized: Counter = Counter()
    lowercase: Counter = Counter()
    for entry in entries:
        text = _normalize(entry.get("corrected") or entry.get("original") or "")
        for m in WORD.finditer(text):
            w = m.group(0)
            if w[:1].islower():
                lowercase[_fold(w)] += 1
                continue
            sentence_start = m.start() == 0 or SENTENCE_END.search(text[: m.start()])
            if not sentence_start and len(w) >= 2 and not w.isdigit():
                capitalized[w] += 1
    return Counter({
        w: n for w, n in capitalized.items()
        if _fold(w) not in known and n > lowercase[_fold(w)]
    })


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--min-count", type=int, default=3)
    args = parser.parse_args()

    entries = TranscriptionHistory().history
    vocabulary = Settings().get("personal_vocabulary", "") or ""
    subs = [(k, n) for k, n in mine_substitutions(entries).most_common() if n >= args.min_count]
    terms = [(k, n) for k, n in mine_terms(entries, vocabulary).most_common(40) if n >= args.min_count]

    out = ensure_app_data_dir() / "replacements_suggestions.txt"
    lines = [
        f"# Gerado a partir de {len(entries)} ditados. Revise e copie o que fizer sentido",
        "# para replacements.txt (substituições) ou para o Vocabulário pessoal (termos).",
        "",
        "## Substituições recorrentes (vezes | regra)",
    ]
    lines += [f"# {n:>4} | {wrong} => {right}" for (wrong, right), n in subs] or ["# (nenhuma)"]
    lines += ["", "## Termos frequentes fora do vocabulário (vezes | termo)"]
    lines += [f"# {n:>4} | {term}" for term, n in terms] or ["# (nenhum)"]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"{len(entries)} ditados analisados | {len(subs)} substituições | {len(terms)} termos")
    print(f"Sugestões: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
