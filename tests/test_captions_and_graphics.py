from rawtoreel.config import FormatPreset, StylePreset
from rawtoreel.render.captions import build_ass, group_lines
from rawtoreel.render.hyperframes import build_html
from rawtoreel.steps.graphics import plan_beats
from tests.test_cutlist import words_from


def fmt(**kw) -> FormatPreset:
    base = {"name": "t", "width": 1080, "height": 1920}
    base.update(kw)
    return FormatPreset.model_validate(base)


def test_group_lines_breaks_on_pause_and_sentence_end():
    ws = words_from("first part here. second part", step=0.4)
    ws[3]["start"] += 1.0  # a pause before "second" (and a sentence end before it)
    for w in ws[3:]:
        w["end"] += 1.0
    groups = group_lines(ws, max_words=4, max_lines=2)
    assert [" ".join(w["w"] for w in g) for g in groups] == ["first part here.", "second part"]


def test_group_lines_respects_word_cap():
    ws = words_from("a b c d e f g h i j", step=0.2)
    groups = group_lines(ws, max_words=3, max_lines=1, max_gap=9, max_span=9)
    assert [len(g) for g in groups] == [3, 3, 3, 1]


def test_ass_highlight_emits_one_event_per_word_and_valid_colours():
    ws = words_from("hello big world")
    ass = build_ass(ws, fmt(captions={"mode": "centered", "highlight": True}), StylePreset(name="s"))
    assert ass.count("Dialogue:") == 3
    assert "&H0066D1FF" in ass  # #ffd166 highlight -> BGR
    assert "PlayResX: 1080" in ass and "Alignment" in ass
    assert "{\\c&H0066D1FF}big{\\c&H00FFFFFF}" in ass


def test_ass_plain_mode_emits_one_event_per_group():
    ws = words_from("hello big world")
    ass = build_ass(ws, fmt(captions={"mode": "bottom", "highlight": False}), StylePreset(name="s"))
    assert ass.count("Dialogue:") == 1


def test_plan_beats_title_lower_third_and_spaced_chapters():
    segs = [{"text": "intro words here", "start": 0.5, "end": 4.0},
            {"text": "Second point starts now, yes indeed", "start": 30.0, "end": 34.0},
            {"text": "too soon", "start": 36.0, "end": 39.0},
            {"text": "Third point is this", "start": 60.0, "end": 64.0}]
    tc = {"duration": 70.0, "words": [], "segments": segs}
    beats = plan_beats(tc, fmt(width=1920, height=1080), StylePreset(name="s"),
                       title="My title", speaker="Chandana", role="AI engineer")
    kinds = [b["type"] for b in beats]
    assert kinds == ["title", "lower_third", "chapter", "chapter"]
    assert beats[2]["text"] == "Second point starts now"  # trailing comma stripped, 5 words max
    assert beats[3]["start"] == 60.0


def test_plan_beats_skips_short_clips_gracefully():
    tc = {"duration": 2.0, "words": [], "segments": []}
    assert plan_beats(tc, fmt(), StylePreset(name="s"), title="t", speaker=None, role=None) == []


def test_build_html_is_a_valid_hyperframes_composition():
    plan = {"job": "j", "duration": 10, "beats": [
        {"type": "title", "start": 0.4, "duration": 3, "text": "A <b>title</b>", "sub": None},
        {"type": "chapter", "start": 5, "duration": 2, "text": "Next"}]}
    html = build_html(plan, fmt(width=1920, height=1080), StylePreset(name="s"))
    assert 'data-composition-id="overlay"' in html and 'data-duration="10"' in html
    assert 'window.__timelines["overlay"] = tl;' in html
    assert "&lt;b&gt;title&lt;/b&gt;" in html  # user text is escaped
    assert html.count("class=\"clip") == 2
    assert "background: transparent" in html
