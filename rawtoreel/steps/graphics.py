"""Step 3 - Graphics: plan the beats from the cut transcript, then render them with HyperFrames.

Outputs: graphics-plan.json (editable), overlay.<format>.webm (transparent layer)

The plan is rule-based and deliberately simple:
  title        - the job title, over the first seconds
  lower_third  - who is speaking (from manifest "speaker"/"role", if set)
  chapter      - a pill with the first words of a sentence that starts after a pause,
                 at most one every graphics.chapter_every_s
  callout      - only from notes.json (step 4); never invented automatically
"""

from __future__ import annotations

import re

from rich.console import Console

from ..config import FormatPreset, StylePreset
from ..job import Job, read_json, write_json
from ..render import hyperframes as hf

console = Console(stderr=True)

_TRAIL = re.compile(r"[\s,.;:!?-]+$")


def _chapter_text(segment_text: str, max_words: int = 5) -> str:
    """First few words of a sentence, stopping at the first clause break (comma, dash, period)."""
    words = segment_text.split()[:max_words]
    for i, tok in enumerate(words):
        if i >= 1 and tok.rstrip().endswith((",", ".", ";", ":", "!", "?", "-", "—")):
            words = words[: i + 1]
            break
    return _TRAIL.sub("", " ".join(words))


def plan_beats(transcript_cut: dict, fmt: FormatPreset, style: StylePreset, *, title: str,
               speaker: str | None, role: str | None, subtitle: str | None = None,
               speech: bool = True) -> list[dict]:
    g = fmt.graphics
    duration = transcript_cut["duration"]
    beats: list[dict] = []
    if g.title_card and duration > style.title_in_s + style.title_hold_s:
        beats.append({"type": "title", "start": style.title_in_s, "duration": style.title_hold_s,
                      "text": title, "sub": subtitle})
    if g.lower_third and speaker and duration > style.lower_third_at_s + style.lower_third_hold_s:
        beats.append({"type": "lower_third", "start": style.lower_third_at_s,
                      "duration": style.lower_third_hold_s, "name": speaker, "role": role})
    if g.chapter_cards and speech:
        last = style.title_in_s + style.title_hold_s if g.title_card else 0.0
        segs = transcript_cut["segments"]
        for i, seg in enumerate(segs):
            if seg["start"] - last < g.chapter_every_s:
                continue
            gap = seg["start"] - segs[i - 1]["end"] if i else 1.0
            if gap < 0.35 or seg["end"] - seg["start"] < 1.5:
                continue
            if seg["start"] + style.chapter_hold_s > duration - 0.5:
                break
            beats.append({"type": "chapter", "start": round(seg["start"], 2),
                          "duration": style.chapter_hold_s, "text": _chapter_text(seg["text"])})
            last = seg["start"]
    return beats


def _apply_notes(beats: list[dict], notes: dict) -> list[dict]:
    """notes.json may drop beats by index, override text, or add callouts."""
    drop = set(notes.get("drop_beats", []))
    beats = [b for i, b in enumerate(beats) if i not in drop]
    for idx, patch in notes.get("edit_beats", {}).items():
        i = int(idx)
        if 0 <= i < len(beats):
            beats[i].update(patch)
    for c in notes.get("callouts", []):
        beats.append({"type": "callout", "start": c["start"], "duration": c.get("duration", 3.0),
                      "text": c["text"]})
    return sorted(beats, key=lambda b: b["start"])


def run(job: Job, fmt: FormatPreset, style: StylePreset, *, render: bool = True) -> dict:
    transcript_cut = read_json(job.transcript_cut)
    m = job.read_manifest()
    beats = plan_beats(transcript_cut, fmt, style, title=job.title,
                       speaker=m.get("speaker"), role=m.get("role"), subtitle=m.get("subtitle"),
                       speech=m["steps"].get("rough_cut", {}).get("speech", True))
    if job.notes.exists():
        beats = _apply_notes(beats, read_json(job.notes))
    plan = {"job": job.name, "format": fmt.name, "width": fmt.width, "height": fmt.height,
            "duration": transcript_cut["duration"], "beats": beats}
    write_json(job.graphics_plan, plan)
    console.log(f"graphics plan: {len(beats)} beats")

    meta = {"beats": len(beats), "format": fmt.name}
    if render and beats:
        project_dir = job.dir / "overlay-src" / fmt.name
        hf.write_project(plan, fmt, style, project_dir)
        out = hf.render(project_dir, job.overlay(fmt.name), fps=fmt.fps)
        meta["overlay"] = out.name
    elif not beats and job.overlay(fmt.name).exists():
        job.overlay(fmt.name).unlink()
    job.mark("graphics", **meta)
    return meta
