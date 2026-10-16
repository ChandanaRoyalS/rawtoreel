"""Make a synthetic "talking head" clip so the pipeline can be demonstrated without any real footage.

The narration deliberately contains the things the rough cut is supposed to remove:
filler words, a restarted sentence, and long pauses. Speech comes from piper (offline TTS);
the picture is a generated gradient with a moving shape so cuts are visible.

    pip install piper-tts
    rawtoreel sample          # downloads the voice (~60 MB) into ~/.cache/piper on first run
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .ffmpeg import run

VOICE = "en_US-lessac-medium"
VOICE_DIR = Path(os.environ.get("PIPER_DATA_DIR", Path.home() / ".cache" / "piper"))

# (sentence, pause_after_seconds)
SCRIPT: list[tuple[str, float]] = [
    ("Hi, I'm testing raw to reel, a small pipeline that edits videos automatically.", 0.4),
    ("Um, so the idea is simple.", 1.6),
    ("You drop a raw clip in a folder and you get a finished video back.", 0.5),
    ("So the first thing it does, so the first thing it does is transcribe the audio with Whisper.", 0.4),
    ("Then it finds filler words, long pauses, and sentences I started twice, and cuts them out.", 2.2),
    ("After that it plans the graphics.", 0.4),
    ("A title card at the start, and chapter markers whenever a new point begins.", 0.5),
    ("Uh, captions are timed to each word, so they land exactly when I say it.", 0.4),
    ("And finally it exports the right size for YouTube, Reels, or TikTok.", 0.3),
    ("Every step writes a plain file you can open and check. That's it.", 0.8),
]


def _tts(text: str, wav: Path) -> None:
    if shutil.which("piper") is None:
        raise RuntimeError("piper not found. Install with: pip install piper-tts && "
                           f"python -m piper.download_voices {VOICE}")
    VOICE_DIR.mkdir(parents=True, exist_ok=True)
    if not (VOICE_DIR / f"{VOICE}.onnx").exists():
        dl = subprocess.run([sys.executable, "-m", "piper.download_voices", "--data-dir", str(VOICE_DIR), VOICE],
                            capture_output=True, text=True)
        if dl.returncode != 0:
            raise RuntimeError("could not download the piper voice: " + dl.stderr[-800:])
    proc = subprocess.run(["piper", "--model", VOICE, "--data-dir", str(VOICE_DIR), "--output_file", str(wav)],
                          input=text, text=True, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr[-1500:])


def make_sample(out: Path, width: int = 1280, height: int = 720) -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmpd = Path(tmp)
        parts: list[Path] = []
        for i, (text, pause) in enumerate(SCRIPT):
            wav = tmpd / f"s{i}.wav"
            _tts(text, wav)
            padded = tmpd / f"p{i}.wav"
            run(["-i", str(wav), "-af", f"apad=pad_dur={pause}", "-ar", "22050", "-ac", "1", str(padded)])
            parts.append(padded)
        lst = tmpd / "list.txt"
        lst.write_text("".join(f"file '{p}'\n" for p in parts), encoding="utf-8")
        speech = tmpd / "speech.wav"
        run(["-f", "concat", "-safe", "0", "-i", str(lst), "-af", "adelay=800|800,apad=pad_dur=1.2", str(speech)])
        dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                    "-of", "csv=p=0", str(speech)], capture_output=True, text=True).stdout)
        # Picture: slow colour wash + a drifting disc so edits are visible in the output.
        vf = (
            f"gradients=s={width}x{height}:c0=#1b1b2f:c1=#3a2d5c:c2=#0f3460:duration={dur:.2f}:speed=0.02,"
            f"drawbox=x='{width // 2 - 110}+sin(t/2)*{width // 5}':y='{height // 2 - 110}':w=220:h=220:"
            f"color=#ff4d6d@0.9:t=fill,"
            f"drawtext=text='rawtoreel sample clip':fontcolor=white@0.8:fontsize={height // 14}:"
            f"x=(w-text_w)/2:y=h-{height // 6}"
        )
        run(["-f", "lavfi", "-i", vf, "-i", str(speech), "-t", f"{dur:.2f}", "-r", "30",
             "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
             "-shortest", str(out)])
    return out
