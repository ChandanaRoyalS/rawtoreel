"""Step 4 - Second pass: the human review hook.

You watch the rough cut, write what you want changed into projects/<job>/notes.json, and
re-run from here. Only the downstream steps re-run (incremental re-composite).

notes.json
{
  "extra_cuts":  [[12.4, 13.9]],              # raw-clip seconds to remove on top of the auto cut
  "restore":     [[30.0, 31.2]],              # raw-clip seconds the auto cut removed but you want back
  "drop_beats":  [2],                         # graphics-plan beat indexes to remove
  "edit_beats":  {"0": {"text": "Better title"}},
  "callouts":    [{"start": 8.0, "duration": 3.0, "text": "Link in description"}],
  "title":       "Override the job title",
  "speaker":     "Chandana", "role": "AI engineer"
}
"""

from __future__ import annotations

from rich.console import Console

from ..cutlist import CutList, Removal, TimeMap, complement, merge_removals
from ..ffmpeg import cut_segments, speech_polish_filter
from ..job import Job, read_json, write_json
from .rough_cut import _resegment, _script_markdown

console = Console(stderr=True)


def run(job: Job) -> dict:
    if not job.notes.exists():
        job.mark("second_pass", applied=False)
        return {"applied": False, "note": "no notes.json; nothing to apply"}

    notes = read_json(job.notes)
    m = job.read_manifest()
    for key in ("title", "speaker", "role"):
        if key in notes:
            m[key] = notes[key]
    job.write_manifest(m)

    changed_cut = bool(notes.get("extra_cuts") or notes.get("restore"))
    if changed_cut:
        cl = CutList.from_dict(read_json(job.cutlist))
        removals = list(cl.removed)
        for s, e in notes.get("extra_cuts", []):
            removals.append(Removal(float(s), float(e), "manual", "second pass"))
        restore = [(float(s), float(e)) for s, e in notes.get("restore", [])]
        removals = [r for r in removals if not any(rs <= r.start and r.end <= re_ for rs, re_ in restore)]
        merged = merge_removals(removals, cl.duration_raw)
        keep = complement(merged, cl.duration_raw, 0.4)
        cl = CutList(duration_raw=cl.duration_raw, keep=keep, removed=merged)
        write_json(job.cutlist, cl.to_dict())
        cut_segments(job.raw, job.cut, cl.keep, audio_filter=speech_polish_filter())
        transcript = read_json(job.transcript)
        words = TimeMap(cl.keep).remap_words(transcript["words"])
        tc = {"language": transcript["language"], "duration": cl.duration_cut,
              "words": words, "segments": _resegment(words)}
        write_json(job.transcript_cut, tc)
        job.script.write_text(_script_markdown(job, tc, cl), encoding="utf-8")
        console.log(f"second pass re-cut: {cl.duration_cut:.1f}s")

    job.mark("second_pass", applied=True, recut=changed_cut)
    return {"applied": True, "recut": changed_cut}
