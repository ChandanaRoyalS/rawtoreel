"""Thin ffmpeg/ffprobe helpers. Every call is logged so a failing step is reproducible by hand."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console

console = Console(stderr=True)


class FFmpegError(RuntimeError):
    pass


def require_tools() -> None:
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            raise FFmpegError(f"{tool} not found on PATH. Install ffmpeg (https://ffmpeg.org/download.html).")


def run(args: list[str], *, quiet: bool = True) -> subprocess.CompletedProcess:
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error" if quiet else "info", *args]
    console.log("[dim]$ " + " ".join(_q(a) for a in cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise FFmpegError(proc.stderr.strip()[-2000:])
    return proc


def _q(a: str) -> str:
    return f'"{a}"' if " " in a else a


@dataclass
class MediaInfo:
    duration: float
    width: int
    height: int
    fps: float
    has_audio: bool
    sample_rate: int


def probe(path: Path) -> MediaInfo:
    proc = subprocess.run(
        [
            "ffprobe", "-v", "error", "-print_format", "json",
            "-show_format", "-show_streams", str(path),
        ],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise FFmpegError(proc.stderr.strip())
    data = json.loads(proc.stdout)
    video = next((s for s in data["streams"] if s["codec_type"] == "video"), None)
    audio = next((s for s in data["streams"] if s["codec_type"] == "audio"), None)
    if video is None:
        raise FFmpegError(f"{path} has no video stream")
    num, den = (video.get("avg_frame_rate") or "30/1").split("/")
    fps = float(num) / float(den) if float(den) else 30.0
    return MediaInfo(
        duration=float(data["format"].get("duration", 0.0)),
        width=int(video["width"]),
        height=int(video["height"]),
        fps=round(fps, 3),
        has_audio=audio is not None,
        sample_rate=int(audio["sample_rate"]) if audio else 0,
    )


def extract_audio(src: Path, dst: Path, sample_rate: int = 16000) -> Path:
    run(["-i", str(src), "-vn", "-ac", "1", "-ar", str(sample_rate), "-c:a", "pcm_s16le", str(dst)])
    return dst


_SILENCE_RE = re.compile(r"silence_(start|end): ([0-9.]+)")


def detect_silences(src: Path, noise_db: float = -35.0, min_s: float = 0.7) -> list[tuple[float, float]]:
    """Return (start, end) spans where the audio is below noise_db for at least min_s."""
    proc = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-nostats", "-i", str(src),
            "-af", f"silencedetect=noise={noise_db}dB:d={min_s}", "-f", "null", "-",
        ],
        capture_output=True, text=True,
    )
    spans: list[tuple[float, float]] = []
    start: float | None = None
    for kind, value in _SILENCE_RE.findall(proc.stderr):
        if kind == "start":
            start = float(value)
        elif kind == "end" and start is not None:
            spans.append((start, float(value)))
            start = None
    return spans


def cut_segments(src: Path, dst: Path, keep: list[tuple[float, float]], *, audio_filter: str = "") -> Path:
    """Keep the given (start, end) spans, in order, and concatenate them with a re-encode.

    A re-encode is used instead of stream-copy so cuts land on exact frames rather than keyframes.
    """
    if not keep:
        raise FFmpegError("cut_segments called with an empty keep list")
    parts = []
    for i, (s, e) in enumerate(keep):
        parts.append(f"[0:v]trim=start={s:.3f}:end={e:.3f},setpts=PTS-STARTPTS[v{i}];")
        parts.append(f"[0:a]atrim=start={s:.3f}:end={e:.3f},asetpts=PTS-STARTPTS[a{i}];")
    streams = "".join(f"[v{i}][a{i}]" for i in range(len(keep)))
    parts.append(f"{streams}concat=n={len(keep)}:v=1:a=1[vc][ac]")
    graph = "".join(parts)
    if audio_filter:
        graph += f";[ac]{audio_filter}[ao]"
        amap = "[ao]"
    else:
        amap = "[ac]"
    run([
        "-i", str(src), "-filter_complex", graph, "-map", "[vc]", "-map", amap,
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(dst),
    ])
    return dst


def speech_polish_filter() -> str:
    """Light audio clean-up for voice: cut rumble, tame harshness, normalise loudness."""
    return "highpass=f=80,lowpass=f=12000,deesser,loudnorm=I=-16:TP=-1.5:LRA=11"


def fit_filter(src_w: int, src_h: int, dst_w: int, dst_h: int, mode: str) -> str:
    """Video filter that maps a source frame onto the target canvas.

    scale    : letterbox/pillarbox onto a solid canvas (never crops)
    crop     : scale to cover, then centre-crop (loses edges, fills frame)
    blur-pad : centre the scaled source over a blurred, zoomed copy of itself
    """
    if mode == "crop":
        return (
            f"scale={dst_w}:{dst_h}:force_original_aspect_ratio=increase,"
            f"crop={dst_w}:{dst_h},setsar=1"
        )
    if mode == "blur-pad":
        return (
            f"split[bg][fg];"
            f"[bg]scale={dst_w}:{dst_h}:force_original_aspect_ratio=increase,"
            f"crop={dst_w}:{dst_h},boxblur=40:8,eq=brightness=-0.15[bgb];"
            f"[fg]scale={dst_w}:{dst_h}:force_original_aspect_ratio=decrease[fgs];"
            f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2,setsar=1"
        )
    return (
        f"scale={dst_w}:{dst_h}:force_original_aspect_ratio=decrease,"
        f"pad={dst_w}:{dst_h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1"
    )
