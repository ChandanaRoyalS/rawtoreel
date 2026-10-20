"""Repo paths and preset loading.

Presets are plain JSON so they can be read and diffed without Python:

- presets/formats/<name>.json  - where the video is going (size, caption position, ...)
- presets/style/<name>.json    - how it looks (colors, fonts, timings)
- presets/caption-corrections.json - words the transcriber gets wrong, fixed upstream
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

REPO_ROOT = Path(os.environ.get("RAWTOREEL_ROOT", Path(__file__).resolve().parent.parent))
PROJECTS_DIR = REPO_ROOT / "projects"
OUTPUTS_DIR = REPO_ROOT / "outputs"
PRESETS_DIR = REPO_ROOT / "presets"
MUSIC_DIR = REPO_ROOT / "music"
OVERLAY_TEMPLATE_DIR = Path(__file__).resolve().parent / "render" / "overlay"


class CaptionLayout(BaseModel):
    mode: Literal["none", "centered", "low", "bottom"] = "bottom"
    font_size: int = 64
    max_words_per_line: int = 5
    max_lines: int = 2
    highlight: bool = True  # karaoke-style word highlight
    margin_v: int = 160  # px from the bottom (or from the vertical centre for "centered")


class GraphicsLayout(BaseModel):
    style: Literal["glass", "cards", "hook"] = "glass"
    title_card: bool = True
    lower_third: bool = True
    chapter_cards: bool = True
    chapter_every_s: float = 25.0
    safe_top: int = 120
    safe_bottom: int = 260


class FormatPreset(BaseModel):
    name: str
    width: int
    height: int
    fps: int = 30
    reframe: Literal["scale", "crop", "blur-pad"] = "scale"
    max_duration_s: float | None = None
    captions: CaptionLayout = Field(default_factory=CaptionLayout)
    graphics: GraphicsLayout = Field(default_factory=GraphicsLayout)
    thumbnail: bool = False
    video_crf: int = 20
    audio_bitrate: str = "160k"

    @property
    def portrait(self) -> bool:
        return self.height > self.width


class StylePreset(BaseModel):
    name: str
    font_family: str = "Inter"
    accent: str = "#ff4d6d"
    accent_2: str = "#ffd166"
    ink: str = "#ffffff"
    paper: str = "#0b0f14"
    caption_fill: str = "#ffffff"
    caption_highlight: str = "#ffd166"
    caption_outline: str = "#000000"
    caption_shadow: bool = True
    title_in_s: float = 0.4
    title_hold_s: float = 3.2
    lower_third_at_s: float = 5.0
    lower_third_hold_s: float = 4.5
    chapter_hold_s: float = 2.4


class RoughCutSettings(BaseModel):
    """Knobs for the automatic cut. Defaults are conservative on purpose."""

    engine: Literal["faster-whisper", "parakeet"] = "faster-whisper"
    model: str = "small"  # faster-whisper size: tiny, base, small, medium, large-v3
    language: str | None = None
    filler_words: list[str] = Field(
        default_factory=lambda: ["um", "uh", "umm", "uhh", "erm", "hmm", "mm", "ah"]
    )
    silence_db: float = -35.0
    min_silence_s: float = 0.7
    keep_pause_s: float = 0.25
    repeat_min_words: int = 3
    repeat_window_s: float = 12.0
    min_segment_s: float = 0.4
    pad_s: float = 0.06
    min_speech_density: float = 0.25  # words per second below which a clip is treated as non-speech


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def load_format(name: str) -> FormatPreset:
    return FormatPreset.model_validate(_load_json(PRESETS_DIR / "formats" / f"{name}.json"))


def load_style(name: str = "default") -> StylePreset:
    return StylePreset.model_validate(_load_json(PRESETS_DIR / "style" / f"{name}.json"))


def load_rough_cut_settings() -> RoughCutSettings:
    path = PRESETS_DIR / "rough-cut.json"
    if path.exists():
        return RoughCutSettings.model_validate(_load_json(path))
    return RoughCutSettings()


def load_caption_corrections() -> dict[str, str]:
    path = PRESETS_DIR / "caption-corrections.json"
    if not path.exists():
        return {}
    data = _load_json(path)
    return {k.lower(): v for k, v in data.get("replace", {}).items()}


def available_formats() -> list[str]:
    return sorted(p.stem for p in (PRESETS_DIR / "formats").glob("*.json"))
