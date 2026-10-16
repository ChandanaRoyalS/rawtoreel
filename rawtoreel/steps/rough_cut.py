"""Step 2 - Rough cut: transcribe, decide the cuts, render cut.mp4, write the script.

Outputs: transcript.json, cutlist.json, cut.mp4, transcript.cut.json, script.md
Re-runs are cheap: the transcript is cached by raw-file hash.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from rich.console import Console

from ..config import RoughCutSettings, load_caption_corrections, load_rough_cut_settings
from ..cutlist import CutList, TimeMap, build_cutlist
from ..ffmpeg import cut_segments, detect_silences, extract_audio, probe, speech_polish_filter
from ..job import Job, file_hash, read_json, write_json
from ..transcribe import transcribe

console = Console(stderr=True)


def _cached_transcript(job: Job, raw: Path, settings: RoughCutSettings) -> dict:
    sha = file_hash(raw)
    if job.transcript.exists():
        t = read_json(job.transcript)
        if t.get("_raw_sha") == sha and t.get("_model") == settings.model:
            console.log("transcript cached")
            return t
    with tempfile.TemporaryDirectory() as tmp:
        wav = extract_audio(raw, Path(tmp) / "audio.wav")
        t = transcribe(wav, model=settings.model, language=settings.language,
                       corrections=load_caption_corrections())
    t["_raw_sha"] = sha
    t["_model"] = settings.model
    write_json(job.transcript, t)
    return t


def _script_markdown(job: Job, transcript: dict, cl: CutList) -> str:
    lines = [f"# {job.title}", "",
             f"Raw {cl.duration_raw:.1f}s -> cut {cl.duration_cut:.1f}s "
             f"({len(cl.removed)} removals)", "", "## Transcript (cut)", ""]
    for seg in transcript["segments"]:
        lines.append(f"- **{seg['start']:.1f}s** {seg['text']}")
    lines += ["", "## Removed", ""]
    for r in cl.removed:
        lines.append(f"- {r.start:.2f}-{r.end:.2f}s [{r.reason}] {r.text}")
    return "\n".join(lines) + "\n"


def run(job: Job, *, settings: RoughCutSettings | None = None, polish_audio: bool = True) -> dict:
    settings = settings or load_rough_cut_settings()
    raw = job.raw
    info = probe(raw)
    transcript = _cached_transcript(job, raw, settings)

    with tempfile.TemporaryDirectory() as tmp:
        wav = extract_audio(raw, Path(tmp) / "audio.wav")
        silences = detect_silences(wav, settings.silence_db, settings.min_silence_s)

    cl = build_cutlist(transcript["words"], silences, info.duration, settings)
    write_json(job.cutlist, cl.to_dict())
    console.log(f"cut: {cl.duration_raw:.1f}s -> {cl.duration_cut:.1f}s, {len(cl.removed)} removals")

    cut_segments(raw, job.cut, cl.keep, audio_filter=speech_polish_filter() if polish_audio else "")

    tm = TimeMap(cl.keep)
    cut_words = tm.remap_words(transcript["words"])
    cut_segments_ = _resegment(cut_words)
    transcript_cut = {
        "language": transcript["language"],
        "duration": cl.duration_cut,
        "words": cut_words,
        "segments": cut_segments_,
    }
    write_json(job.transcript_cut, transcript_cut)
    job.script.write_text(_script_markdown(job, transcript_cut, cl), encoding="utf-8")

    meta = {"duration_raw": cl.duration_raw, "duration_cut": cl.duration_cut,
            "removals": len(cl.removed), "words": len(cut_words)}
    job.mark("rough_cut", **meta)
    return meta


def _resegment(words: list[dict], max_gap: float = 0.8, max_words: int = 18) -> list[dict]:
    """Group cut words back into sentence-ish segments for the script and chapter detection."""
    segs: list[dict] = []
    cur: list[dict] = []
    for w in words:
        if cur and (w["start"] - cur[-1]["end"] > max_gap or len(cur) >= max_words
                    or cur[-1]["w"].endswith((".", "?", "!"))):
            segs.append(_seg(cur))
            cur = []
        cur.append(w)
    if cur:
        segs.append(_seg(cur))
    return segs


def _seg(ws: list[dict]) -> dict:
    return {"text": " ".join(w["w"] for w in ws), "start": ws[0]["start"], "end": ws[-1]["end"]}
