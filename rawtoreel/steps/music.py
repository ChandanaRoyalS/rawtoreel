"""Step 6 - Background music (optional): pick a bed, loop it to length, duck it under the voice.

Outputs: music.wav  - the ducked bed, already at mix level; export just adds it.

Tracks come from music/ (anything .wav/.mp3/.m4a/.ogg). The repo ships no third-party audio;
see music/README.md for where to get CC0 tracks. With an empty folder the step synthesises a soft
ambient pad with ffmpeg so the pipeline (and CI) still runs end to end. That pad is generated
from sine waves on the spot, so there is nothing to license.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from rich.console import Console

from ..config import MUSIC_DIR
from ..ffmpeg import probe
from ..ffmpeg import run as ffmpeg
from ..job import Job

console = Console(stderr=True)

AUDIO_EXT = {".wav", ".mp3", ".m4a", ".ogg", ".flac"}


def available_tracks() -> list[Path]:
    if not MUSIC_DIR.exists():
        return []
    return sorted(p for p in MUSIC_DIR.iterdir() if p.suffix.lower() in AUDIO_EXT)


def synth_pad(dst: Path, duration: float, seed: str = "rawtoreel") -> Path:
    """A slow, chord-like pad: three detuned sines with a gentle tremolo. Deterministic per seed."""
    h = int(hashlib.sha1(seed.encode()).hexdigest(), 16)
    root = [110.0, 130.81, 146.83, 164.81][h % 4]  # A2, C3, D3, E3
    f1, f2, f3 = root, root * 1.5, root * 2.0 * 1.003
    expr = (
        f"0.18*sin(2*PI*{f1}*t)+0.12*sin(2*PI*{f2}*t)+0.08*sin(2*PI*{f3}*t)"
        f"+0.05*sin(2*PI*{f1 * 0.5}*t)"
    )
    ffmpeg([
        "-f", "lavfi", "-i", f"aevalsrc={expr}:s=48000:d={duration:.3f}",
        "-af", f"tremolo=f=0.15:d=0.35,lowpass=f=1800,afade=t=in:d=2,afade=t=out:st={max(0, duration - 3):.3f}:d=3",
        "-ac", "2", str(dst),
    ])
    return dst


def run_step(job: Job, *, track: str | None = None, level_db: float = -22.0,
             duck_db: float = -14.0) -> dict:
    cut = job.cut
    duration = probe(cut).duration
    tracks = available_tracks()
    if track:
        src = MUSIC_DIR / track
        if not src.exists():
            raise FileNotFoundError(src)
    elif tracks:
        src = tracks[int(hashlib.sha1(job.name.encode()).hexdigest(), 16) % len(tracks)]
    else:
        src = synth_pad(job.dir / "music.bed.wav", duration + 2, seed=job.name)
        console.log("music/ is empty; using a synthesised pad")

    # Loop the bed to length, then sidechain-duck it against the speech from the cut.
    graph = (
        f"[1:a]aloop=loop=-1:size=2e9,atrim=0:{duration:.3f},asetpts=PTS-STARTPTS,"
        f"volume={level_db}dB[bed];"
        f"[0:a]aformat=channel_layouts=stereo[voice];"
        f"[bed][voice]sidechaincompress=threshold=0.05:ratio=8:attack=40:release=500:"
        f"makeup=1:level_sc=1[ducked]"
    )
    ffmpeg([
        "-i", str(cut), "-i", str(src), "-filter_complex", graph, "-map", "[ducked]",
        "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(job.music),
    ])
    meta = {"track": src.name, "level_db": level_db}
    job.mark("music", **meta)
    return meta


run = run_step  # the step entry point
