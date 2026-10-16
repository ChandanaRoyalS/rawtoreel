"""A job is one raw clip moving through the pipeline.

Everything lives under projects/<job>/ so each step's output is a plain file
you can open, diff, or hand-edit before the next step runs:

    projects/<job>/
      raw/<original>            step 1
      transcript.json           step 2  word-level transcript of the raw clip
      cutlist.json              step 2  what was kept / removed and why
      cut.mp4                   step 2  the rough cut
      transcript.cut.json       step 2  transcript re-timed to the cut
      script.md                 step 2  readable transcript
      graphics-plan.json        step 3  beats: title, lower-third, chapters
      overlay.<format>.webm     step 3  transparent graphics layer
      notes.json                step 4  your manual overrides (optional)
      captions.<format>.ass     step 5
      music.wav                 step 6  ducked bed (optional)
      manifest.json             step status + input hashes

    outputs/<job>.<format>.mp4  step 7
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path

from . import STEPS
from .config import OUTPUTS_DIR, PROJECTS_DIR


@dataclass
class Job:
    name: str
    root: Path = PROJECTS_DIR

    # -- paths -------------------------------------------------------------
    @property
    def dir(self) -> Path:
        return self.root / self.name

    @property
    def raw_dir(self) -> Path:
        return self.dir / "raw"

    @property
    def raw(self) -> Path:
        files = sorted(p for p in self.raw_dir.iterdir() if p.is_file()) if self.raw_dir.exists() else []
        if not files:
            raise FileNotFoundError(f"No raw clip in {self.raw_dir}. Run: rawtoreel intake {self.name} <file>")
        return files[0]

    @property
    def transcript(self) -> Path:
        return self.dir / "transcript.json"

    @property
    def cutlist(self) -> Path:
        return self.dir / "cutlist.json"

    @property
    def cut(self) -> Path:
        return self.dir / "cut.mp4"

    @property
    def transcript_cut(self) -> Path:
        return self.dir / "transcript.cut.json"

    @property
    def script(self) -> Path:
        return self.dir / "script.md"

    @property
    def graphics_plan(self) -> Path:
        return self.dir / "graphics-plan.json"

    def overlay(self, fmt: str) -> Path:
        return self.dir / f"overlay.{fmt}.webm"

    @property
    def notes(self) -> Path:
        return self.dir / "notes.json"

    def captions(self, fmt: str) -> Path:
        return self.dir / f"captions.{fmt}.ass"

    @property
    def music(self) -> Path:
        return self.dir / "music.wav"

    @property
    def manifest(self) -> Path:
        return self.dir / "manifest.json"

    def output(self, fmt: str) -> Path:
        return OUTPUTS_DIR / f"{self.name}.{fmt}.mp4"

    def report(self, fmt: str) -> Path:
        return OUTPUTS_DIR / f"{self.name}.{fmt}.json"

    # -- manifest ----------------------------------------------------------
    def read_manifest(self) -> dict:
        if self.manifest.exists():
            return json.loads(self.manifest.read_text(encoding="utf-8"))
        return {"job": self.name, "steps": {}, "title": self.name.replace("-", " ").title()}

    def write_manifest(self, data: dict) -> None:
        self.manifest.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def mark(self, step: str, **info) -> None:
        m = self.read_manifest()
        m["steps"][step] = {"done_at": time.strftime("%Y-%m-%dT%H:%M:%S"), **info}
        self.write_manifest(m)

    def is_done(self, step: str) -> bool:
        return step in self.read_manifest()["steps"]

    @property
    def title(self) -> str:
        return self.read_manifest().get("title", self.name)

    def set_title(self, title: str) -> None:
        m = self.read_manifest()
        m["title"] = title
        self.write_manifest(m)

    def status(self) -> list[tuple[str, bool]]:
        m = self.read_manifest()
        return [(s, s in m["steps"]) for s in STEPS]


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
