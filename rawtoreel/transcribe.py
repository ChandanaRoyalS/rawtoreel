"""Speech-to-text with word timestamps.

Two engines, chosen by presets/rough-cut.json "engine":
  faster-whisper  (default) multilingual Whisper via CTranslate2; model from Hugging Face
  parakeet        NVIDIA Parakeet-TDT 0.6B v2 via sherpa-onnx; English only, ~8x faster on CPU,
                  model (~480 MB int8) fetched from the sherpa-onnx GitHub release

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
               corrections: dict[str, str] | None = None, engine: str = "faster-whisper") -> dict:
    if engine == "parakeet":
        result = _transcribe_parakeet(audio)
    elif engine == "faster-whisper":
        result = _transcribe_whisper(audio, model=model, language=language)
    else:
        raise ValueError(f"unknown transcription engine '{engine}' (use faster-whisper or parakeet)")
    if corrections:
        apply_corrections(result["words"], corrections)
        for s in result["segments"]:
            s["text"] = correct_text(s["text"], corrections)
    return result


def _transcribe_whisper(audio: Path, *, model: str, language: str | None) -> dict:
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
    return {
        "language": info.language,
        "duration": round(info.duration, 3),
        "words": words,
        "segments": segments,
    }


# --------------------------------------------------------------------------- parakeet (sherpa-onnx)

PARAKEET_NAME = "sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8"
PARAKEET_URL = f"https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/{PARAKEET_NAME}.tar.bz2"


def _parakeet_dir() -> Path:
    import os
    import tarfile
    import urllib.request

    cache = Path(os.environ.get("RAWTOREEL_MODEL_DIR", Path.home() / ".cache" / "sherpa-onnx"))
    d = cache / PARAKEET_NAME
    if (d / "encoder.int8.onnx").exists():
        return d
    cache.mkdir(parents=True, exist_ok=True)
    console.log(f"downloading {PARAKEET_NAME} (~480 MB, once)")
    tar_path = cache / f"{PARAKEET_NAME}.tar.bz2"
    urllib.request.urlretrieve(PARAKEET_URL, tar_path)
    with tarfile.open(tar_path, "r:bz2") as tf:
        tf.extractall(cache, filter="data")
    tar_path.unlink()
    return d


def _transcribe_parakeet(audio: Path) -> dict:
    import wave

    import numpy as np
    import sherpa_onnx  # imported lazily: heavy

    d = _parakeet_dir()
    rec = sherpa_onnx.OfflineRecognizer.from_transducer(
        encoder=str(d / "encoder.int8.onnx"), decoder=str(d / "decoder.int8.onnx"),
        joiner=str(d / "joiner.int8.onnx"), tokens=str(d / "tokens.txt"),
        num_threads=4, model_type="nemo_transducer",
    )
    with wave.open(str(audio)) as wf:
        assert wf.getframerate() == 16000 and wf.getnchannels() == 1, "expected 16 kHz mono wav"
        samples = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    duration = len(samples) / 16000
    stream = rec.create_stream()
    stream.accept_waveform(16000, samples)
    rec.decode_stream(stream)
    r = stream.result
    words = _words_from_tokens(list(r.tokens), list(r.timestamps), duration)
    return {"language": "en", "duration": round(duration, 3), "words": words, "segments": _segments(words)}


def _words_from_tokens(tokens: list[str], stamps: list[float], duration: float, tok_len: float = 0.08) -> list[Word]:
    """SentencePiece tokens start a new word with a leading space. Each token carries its start time;
    a word ends where the next word starts (capped) or a little after its last token."""
    words: list[Word] = []
    for tok, t in zip(tokens, stamps, strict=False):
        if tok.startswith(" ") or not words:
            words.append({"w": tok.strip(), "start": round(t, 3), "end": round(t + tok_len, 3), "p": 1.0})
        else:
            words[-1]["w"] += tok
            words[-1]["end"] = round(t + tok_len, 3)
    for a, b in zip(words, words[1:], strict=False):
        a["end"] = round(min(max(a["end"], a["start"] + 0.05), b["start"]), 3)
    if words:
        words[-1]["end"] = round(min(words[-1]["end"] + 0.15, duration), 3)
    return [w for w in words if w["w"]]


def _segments(words: list[Word], max_gap: float = 0.8, max_words: int = 18) -> list[dict]:
    segs: list[dict] = []
    cur: list[Word] = []
    for w in words:
        if cur and (w["start"] - cur[-1]["end"] > max_gap or len(cur) >= max_words
                    or cur[-1]["w"].endswith((".", "?", "!"))):
            segs.append({"text": " ".join(x["w"] for x in cur), "start": cur[0]["start"], "end": cur[-1]["end"]})
            cur = []
        cur.append(w)
    if cur:
        segs.append({"text": " ".join(x["w"] for x in cur), "start": cur[0]["start"], "end": cur[-1]["end"]})
    return segs


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
