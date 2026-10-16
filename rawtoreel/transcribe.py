"""Speech-to-text with word timestamps via faster-whisper (CTranslate2, CPU-friendly).

Output shape (transcript.json):
{
  "language": "en",
  "duration": 27.3,
  "words": [{"w": "Hello", "start": 0.31, "end": 0.58, "p": 0.98}, ...],
  "segments": [{"text": "Hello and welcome.", "start": 0.31, "end": 1.9}, ...]
}
"""

from __future__ import annotations

import re
from pathlib import Path

from rich.console import Console

console = Console(stderr=True)

Word = dict  # {"w": str, "start": float, "end": float, "p": float}


def transcribe(audio: Path, *, model: str = "small", language: str | None = None,
               corrections: dict[str, str] | None = None) -> dict:
    from faster_whisper import WhisperModel  # imported lazily: heavy

    console.log(f"loading faster-whisper model '{model}' (first run downloads it)")
    wm = WhisperModel(model, device="cpu", compute_type="int8")
    segments_iter, info = wm.transcribe(
        str(audio),
        language=language,
        word_timestamps=True,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 400},
        beam_size=5,
        condition_on_previous_text=False,
    )
    words: list[Word] = []
    segments: list[dict] = []
    for seg in segments_iter:
        segments.append({"text": seg.text.strip(), "start": round(seg.start, 3), "end": round(seg.end, 3)})
        for w in seg.words or []:
            token = w.word.strip()
            if not token:
                continue
            words.append({"w": token, "start": round(w.start, 3), "end": round(w.end, 3), "p": round(w.probability, 3)})
    if corrections:
        apply_corrections(words, corrections)
        for s in segments:
            s["text"] = correct_text(s["text"], corrections)
    return {
        "language": info.language,
        "duration": round(info.duration, 3),
        "words": words,
        "segments": segments,
    }


_PUNCT = re.compile(r"^(\W*)(.*?)(\W*)$", re.DOTALL)


def apply_corrections(words: list[Word], corrections: dict[str, str]) -> None:
    """Fix brand names / spellings the model gets wrong, keeping surrounding punctuation."""
    for w in words:
        lead, core, trail = _PUNCT.match(w["w"]).groups()
        fixed = corrections.get(core.lower())
        if fixed:
            w["w"] = f"{lead}{fixed}{trail}"


def correct_text(text: str, corrections: dict[str, str]) -> str:
    def sub(m: re.Match) -> str:
        return corrections.get(m.group(0).lower(), m.group(0))

    return re.sub(r"[A-Za-z0-9']+", sub, text)


def words_to_text(words: list[Word]) -> str:
    return " ".join(w["w"] for w in words)
