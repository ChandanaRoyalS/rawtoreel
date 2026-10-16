"""Step 1 - Intake: copy the raw clip into projects/<job>/raw/ and record what it is.

The original is never modified; every later step reads from this copy.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from ..ffmpeg import probe, require_tools
from ..job import Job, file_hash


def run(job: Job, source: Path, *, title: str | None = None) -> dict:
    require_tools()
    source = Path(source)
    if not source.exists():
        raise FileNotFoundError(source)
    job.raw_dir.mkdir(parents=True, exist_ok=True)
    dest = job.raw_dir / source.name
    if not dest.exists() or file_hash(dest) != file_hash(source):
        for old in job.raw_dir.iterdir():
            old.unlink()
        shutil.copy2(source, dest)
    info = probe(dest)
    if not info.has_audio:
        raise ValueError("The clip has no audio track; the rough cut needs speech to work with.")
    meta = {
        "file": dest.name,
        "sha": file_hash(dest),
        "duration": info.duration,
        "width": info.width,
        "height": info.height,
        "fps": info.fps,
    }
    if title:
        job.set_title(title)
    job.mark("intake", **meta)
    return meta
