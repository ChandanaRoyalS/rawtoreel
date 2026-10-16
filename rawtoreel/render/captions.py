"""Build an .ass subtitle file from word timings. ffmpeg burns it in with libass.

Two looks, driven by the format preset:
  highlight=True  - every word is its own event; the spoken word is tinted (karaoke feel)
  highlight=False - plain line captions

Lines are built from word timings, never from raw sentences, so they stay on-beat with the cut.
"""

from __future__ import annotations

from ..config import FormatPreset, StylePreset


def _ass_color(hex_rgb: str, alpha: int = 0) -> str:
    """#RRGGBB -> &HAABBGGRR (ASS is BGR with inverted alpha, 00 = opaque)."""
    h = hex_rgb.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def _ts(t: float) -> str:
    t = max(0.0, t)
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def group_lines(words: list[dict], max_words: int, max_lines: int, max_gap: float = 0.6,
                max_span: float = 3.2) -> list[list[dict]]:
    """Chunk words into caption groups of <= max_words*max_lines, breaking on pauses and punctuation."""
    cap = max_words * max_lines
    groups: list[list[dict]] = []
    cur: list[dict] = []
    for w in words:
        if cur:
            gap = w["start"] - cur[-1]["end"]
            span = w["end"] - cur[0]["start"]
            ends_sentence = cur[-1]["w"].rstrip().endswith((".", "?", "!"))
            if gap > max_gap or span > max_span or len(cur) >= cap or (ends_sentence and len(cur) >= 2):
                groups.append(cur)
                cur = []
        cur.append(w)
    if cur:
        groups.append(cur)
    return groups


def _wrap(words: list[dict], max_words: int) -> list[list[dict]]:
    return [words[i:i + max_words] for i in range(0, len(words), max_words)]


def build_ass(words: list[dict], fmt: FormatPreset, style: StylePreset) -> str:
    cap = fmt.captions
    W, H = fmt.width, fmt.height
    base = min(W, H) / 1080
    size = int(cap.font_size * base)
    outline = max(2, int(4 * base))
    shadow = int(2 * base) if style.caption_shadow else 0

    if cap.mode == "centered":
        align, margin_v = 5, 0  # centre of frame
    elif cap.mode == "low":
        align, margin_v = 2, int(cap.margin_v * base)  # bottom-centre, high margin: "under the face"
    else:
        align, margin_v = 2, int(cap.margin_v * base)

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{style.font_family},{size},{_ass_color(style.caption_fill)},{_ass_color(style.caption_highlight)},{_ass_color(style.caption_outline)},{_ass_color("#000000", 0x60)},-1,0,0,0,100,100,0,0,1,{outline},{shadow},{align},{int(80 * base)},{int(80 * base)},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    hl = _ass_color(style.caption_highlight)
    fill = _ass_color(style.caption_fill)
    events: list[str] = []
    for group in group_lines(words, cap.max_words_per_line, cap.max_lines):
        lines = _wrap(group, cap.max_words_per_line)
        g_start, g_end = group[0]["start"], group[-1]["end"] + 0.15
        if not cap.highlight:
            text = "\\N".join(" ".join(w["w"] for w in line) for line in lines)
            events.append(f"Dialogue: 0,{_ts(g_start)},{_ts(g_end)},Cap,,0,0,0,,{text}")
            continue
        # One event per spoken word; the whole group stays visible, only the colour moves.
        for idx, w in enumerate(group):
            start = w["start"] if idx else g_start
            end = group[idx + 1]["start"] if idx + 1 < len(group) else g_end
            if end <= start:
                continue
            rendered = []
            k = 0
            for line in lines:
                parts = []
                for lw in line:
                    tok = lw["w"].replace("{", "(").replace("}", ")")
                    if k == idx:
                        parts.append(f"{{\\c{hl}}}{tok}{{\\c{fill}}}")
                    else:
                        parts.append(tok)
                    k += 1
                rendered.append(" ".join(parts))
            text = "\\N".join(rendered)
            events.append(f"Dialogue: 0,{_ts(start)},{_ts(end)},Cap,,0,0,0,,{text}")
    return header + "\n".join(events) + "\n"
