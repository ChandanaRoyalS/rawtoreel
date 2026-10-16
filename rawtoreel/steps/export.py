"""Step 7 - Export: composite everything and promote to outputs/<job>.<format>.mp4

cut.mp4  + overlay.<format>.webm (alpha)  + captions.<format>.ass  + music.wav
   |             |                              |                        |
   fit to format ─ overlay ─────────────────── burn in ─────── mix ─────┴──> final.mp4

Also writes outputs/<job>.<format>.json (what went in, durations, sizes) and an optional thumbnail.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from rich.console import Console

from ..config import OUTPUTS_DIR, FormatPreset
from ..ffmpeg import fit_filter, probe
from ..ffmpeg import run as ffmpeg
from ..job import Job, file_hash, write_json

console = Console(stderr=True)


def _ass_path_escape(p: Path) -> str:
    s = str(p).replace("\\", "/")
    return s.replace(":", "\\:").replace("'", "\\'")


def run_step(job: Job, fmt: FormatPreset, *, prune: bool = False) -> dict:
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    cut = job.cut
    info = probe(cut)
    overlay = job.overlay(fmt.name) if job.overlay(fmt.name).exists() else None
    captions = job.captions(fmt.name) if job.captions(fmt.name).exists() else None
    music = job.music if job.music.exists() else None
    out = job.output(fmt.name)

    inputs: list[str] = ["-i", str(cut)]
    idx = 1
    graph = f"[0:v]{fit_filter(info.width, info.height, fmt.width, fmt.height, fmt.reframe)}[base];"
    last_v = "[base]"
    if overlay:
        inputs += ["-c:v", "libvpx-vp9", "-i", str(overlay)]  # vp9 decoder keeps the alpha plane
        graph += f"[{idx}:v]format=yuva420p[ov];{last_v}[ov]overlay=0:0:format=auto:shortest=0[withov];"
        last_v = "[withov]"
        idx += 1
    if captions:
        graph += f"{last_v}ass='{_ass_path_escape(captions)}'[withcap];"
        last_v = "[withcap]"
    graph += f"{last_v}format=yuv420p[vout];"

    if music:
        inputs += ["-i", str(music)]
        graph += (f"[0:a]aformat=channel_layouts=stereo[voice];[{idx}:a]aformat=channel_layouts=stereo[bed];"
                  f"[voice][bed]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=11[aout]")
        idx += 1
    else:
        graph += "[0:a]loudnorm=I=-16:TP=-1.5:LRA=11[aout]"

    args = [*inputs, "-filter_complex", graph, "-map", "[vout]", "-map", "[aout]",
            "-r", str(fmt.fps), "-c:v", "libx264", "-preset", "medium", "-crf", str(fmt.video_crf),
            "-profile:v", "high", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", fmt.audio_bitrate,
            "-ar", "48000", "-movflags", "+faststart"]
    if fmt.max_duration_s:
        args += ["-t", f"{fmt.max_duration_s:.2f}"]
    args.append(str(out))
    ffmpeg(args)

    final = probe(out)
    report = {
        "job": job.name, "format": fmt.name, "output": out.name, "sha": file_hash(out),
        "duration_s": final.duration, "width": final.width, "height": final.height, "fps": final.fps,
        "size_bytes": out.stat().st_size,
        "inputs": {"cut": cut.name, "overlay": overlay.name if overlay else None,
                   "captions": captions.name if captions else None, "music": music.name if music else None},
        "steps": job.read_manifest()["steps"],
    }
    thumb = None
    if fmt.thumbnail:
        thumb = out.with_suffix(".jpg")
        ffmpeg(["-ss", f"{final.duration / 3:.2f}", "-i", str(out), "-frames:v", "1", "-q:v", "2", str(thumb)])
        report["thumbnail"] = thumb.name
    write_json(job.report(fmt.name), report)
    console.log(f"exported {out} ({final.duration:.1f}s, {out.stat().st_size / 1e6:.1f} MB)")

    if prune:
        for p in (job.dir / "overlay-src", job.dir / "music.bed.wav"):
            if p.is_dir():
                shutil.rmtree(p)
            elif p.exists():
                os.remove(p)
    job.mark("export", output=out.name, duration=final.duration)
    return report


run = run_step  # the step entry point
