"""Decide what to cut. Pure functions over a word-level transcript, so this is unit-testable
without ffmpeg or a model.

Three kinds of removal, each tagged with a reason so you can audit cutlist.json:

  filler   - "um", "uh", ... (configurable list)
  silence  - a pause longer than min_silence_s, shortened to keep_pause_s
  repeat   - a restarted take: the same N+ words said again within a short window;
             the FIRST attempt is removed, the last (usually best) one is kept
  edges    - dead air before the first word and after the last one
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .config import RoughCutSettings

Span = tuple[float, float]


@dataclass
class Removal:
    start: float
    end: float
    reason: str
    text: str = ""


@dataclass
class CutList:
    duration_raw: float
    keep: list[Span]
    removed: list[Removal] = field(default_factory=list)

    @property
    def duration_cut(self) -> float:
        return round(sum(e - s for s, e in self.keep), 3)

    def to_dict(self) -> dict:
        return {
            "duration_raw": round(self.duration_raw, 3),
            "duration_cut": self.duration_cut,
            "keep": [[round(s, 3), round(e, 3)] for s, e in self.keep],
            "removed": [
                {"start": round(r.start, 3), "end": round(r.end, 3), "reason": r.reason, "text": r.text}
                for r in self.removed
            ],
        }

    @classmethod
    def from_dict(cls, d: dict) -> CutList:
        return cls(
            duration_raw=d["duration_raw"],
            keep=[(s, e) for s, e in d["keep"]],
            removed=[Removal(**r) for r in d.get("removed", [])],
        )


_norm_re = re.compile(r"[^a-z0-9']+")


def norm(token: str) -> str:
    return _norm_re.sub("", token.lower())


# --------------------------------------------------------------------------- detectors

def find_fillers(words: list[dict], fillers: set[str], pad: float) -> list[Removal]:
    out = []
    for w in words:
        if norm(w["w"]) in fillers:
            out.append(Removal(w["start"] - pad, w["end"] + pad, "filler", w["w"]))
    return out


def find_silences(silences: list[Span], min_silence_s: float, keep_pause_s: float) -> list[Removal]:
    out = []
    for s, e in silences:
        if e - s >= min_silence_s:
            half = keep_pause_s / 2
            out.append(Removal(s + half, e - half, "silence", f"{e - s:.1f}s pause"))
    return out


def find_repeats(words: list[dict], min_words: int, window_s: float) -> list[Removal]:
    """A restart is: phrase P spoken at i, then P spoken again at j>i within window_s.
    Remove [words[i].start, words[j].start): the first take plus whatever trailed off.
    Also catches single-word stutters ("the the", "I- I").
    """
    toks = [norm(w["w"]) for w in words]
    n = len(toks)
    out: list[Removal] = []
    i = 0
    while i < n:
        hit = None
        # longest match first so "so what I did was" beats "so what"
        for j in range(i + 1, n):
            if words[j]["start"] - words[i]["start"] > window_s:
                break
            length = 0
            while i + length < j and j + length < n and toks[i + length] == toks[j + length] and toks[i + length]:
                length += 1
            if length >= min_words or (length >= 1 and j == i + 1 and length == 1):
                hit = (j, length)
                if length >= min_words:
                    break
        if hit:
            j, length = hit
            text = " ".join(w["w"] for w in words[i:j])
            out.append(Removal(words[i]["start"], words[j]["start"], "repeat", text))
            i = j
        else:
            i += 1
    return out


def find_edges(words: list[dict], duration: float, lead_in: float = 0.35, tail: float = 0.5) -> list[Removal]:
    if not words:
        return []
    out = []
    first, last = words[0]["start"], words[-1]["end"]
    if first - lead_in > 0.05:
        out.append(Removal(0.0, first - lead_in, "edges", "dead air before speech"))
    if duration - (last + tail) > 0.05:
        out.append(Removal(last + tail, duration, "edges", "dead air after speech"))
    return out


# --------------------------------------------------------------------------- assembly

def merge_removals(removals: list[Removal], duration: float) -> list[Removal]:
    rs = sorted((Removal(max(0.0, r.start), min(duration, r.end), r.reason, r.text) for r in removals),
                key=lambda r: r.start)
    merged: list[Removal] = []
    for r in rs:
        if r.end <= r.start:
            continue
        if merged and r.start <= merged[-1].end:
            last = merged[-1]
            last.end = max(last.end, r.end)
            if r.reason not in last.reason:
                last.reason = f"{last.reason}+{r.reason}"
            last.text = (last.text + " | " + r.text).strip(" |")
        else:
            merged.append(r)
    return merged


def complement(removals: list[Removal], duration: float, min_segment_s: float) -> list[Span]:
    keep: list[Span] = []
    cursor = 0.0
    for r in removals:
        if r.start - cursor >= min_segment_s:
            keep.append((cursor, r.start))
        cursor = max(cursor, r.end)
    if duration - cursor >= min_segment_s:
        keep.append((cursor, duration))
    return keep


def build_cutlist(words: list[dict], silences: list[Span], duration: float,
                  settings: RoughCutSettings | None = None) -> CutList:
    st = settings or RoughCutSettings()
    removals = (
        find_fillers(words, set(st.filler_words), st.pad_s)
        + find_silences(silences, st.min_silence_s, st.keep_pause_s)
        + find_repeats(words, st.repeat_min_words, st.repeat_window_s)
        + find_edges(words, duration)
    )
    merged = merge_removals(removals, duration)
    keep = complement(merged, duration, st.min_segment_s)
    if not keep:  # never produce an empty video
        keep = [(0.0, duration)]
        merged = []
    return CutList(duration_raw=duration, keep=keep, removed=merged)


# --------------------------------------------------------------------------- remapping

class TimeMap:
    """Maps raw-clip time to cut-clip time given the kept spans."""

    def __init__(self, keep: list[Span]):
        self.keep = keep
        self.offsets: list[float] = []
        acc = 0.0
        for s, e in keep:
            self.offsets.append(acc)
            acc += e - s

    def to_cut(self, t: float) -> float | None:
        for (s, e), off in zip(self.keep, self.offsets, strict=True):
            if s <= t <= e:
                return round(off + (t - s), 3)
        return None

    def remap_words(self, words: list[dict]) -> list[dict]:
        out = []
        for w in words:
            mid = (w["start"] + w["end"]) / 2
            if self.to_cut(mid) is None:
                continue
            s = self.to_cut(w["start"])
            e = self.to_cut(w["end"])
            if s is None:
                s = self.to_cut(mid)
            if e is None:
                e = self.to_cut(mid)
            out.append({**w, "start": s, "end": max(e, s + 0.05)})
        return out
