"""Step 5 - Captions: word-timed .ass subtitles for the cut, styled per format.

Outputs: captions.<format>.ass   (skipped when the format preset says mode: none, e.g. YouTube,
                                  where platform captions are better than burned-in ones)
Also writes captions.<format>.srt so you can upload captions to the platform instead.
"""

from __future__ import annotations

from rich.console import Console

from ..config import FormatPreset, StylePreset
from ..job import Job, read_json
from ..render.captions import build_ass, group_lines

console = Console(stderr=True)


def _srt(words: list[dict], fmt: FormatPreset) -> str:
    def ts(t: float) -> str:
        ms = int(round(t * 1000))
        h, ms = divmod(ms, 3_600_000)
        m, ms = divmod(ms, 60_000)
        s, ms = divmod(ms, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    out = []
    for i, g in enumerate(group_lines(words, fmt.captions.max_words_per_line, fmt.captions.max_lines), 1):
        out.append(f"{i}\n{ts(g[0]['start'])} --> {ts(g[-1]['end'] + 0.15)}\n{' '.join(w['w'] for w in g)}\n")
    return "\n".join(out)


def run(job: Job, fmt: FormatPreset, style: StylePreset) -> dict:
    tc = read_json(job.transcript_cut)
    words = tc["words"]
    srt_path = job.captions(fmt.name).with_suffix(".srt")
    srt_path.write_text(_srt(words, fmt), encoding="utf-8")
    if fmt.captions.mode == "none":
        if job.captions(fmt.name).exists():
            job.captions(fmt.name).unlink()
        job.mark("captions", burned=False, srt=srt_path.name)
        return {"burned": False, "srt": srt_path.name}
    job.captions(fmt.name).write_text(build_ass(words, fmt, style), encoding="utf-8")
    console.log(f"captions: {len(words)} words -> {job.captions(fmt.name).name}")
    job.mark("captions", burned=True, srt=srt_path.name, words=len(words))
    return {"burned": True, "words": len(words)}
