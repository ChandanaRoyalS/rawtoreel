"""The rough-cut decision logic, tested without ffmpeg or a speech model."""

from rawtoreel.config import RoughCutSettings
from rawtoreel.cutlist import (
    TimeMap,
    build_cutlist,
    complement,
    find_edges,
    find_fillers,
    find_repeats,
    find_silences,
    merge_removals,
)


def words_from(text: str, start: float = 0.0, step: float = 0.4) -> list[dict]:
    out = []
    t = start
    for tok in text.split():
        out.append({"w": tok, "start": round(t, 3), "end": round(t + step * 0.8, 3), "p": 0.9})
        t += step
    return out


def test_fillers_are_removed_with_padding():
    ws = words_from("so um the plan is uh simple")
    rem = find_fillers(ws, {"um", "uh"}, pad=0.05)
    assert [r.text for r in rem] == ["um", "uh"]
    assert rem[0].start == ws[1]["start"] - 0.05
    assert all(r.reason == "filler" for r in rem)


def test_filler_matching_ignores_punctuation_and_case():
    ws = words_from("Um, yes. Uh... right")
    rem = find_fillers(ws, {"um", "uh"}, pad=0.0)
    assert [r.text for r in rem] == ["Um,", "Uh..."]


def test_long_silences_are_shortened_not_deleted():
    rem = find_silences([(10.0, 12.0), (20.0, 20.3)], min_silence_s=0.7, keep_pause_s=0.3)
    assert len(rem) == 1
    assert (rem[0].start, rem[0].end) == (10.15, 11.85)  # 0.15 s kept on each side


def test_restarted_sentence_keeps_the_second_take():
    ws = words_from("so the first thing I so the first thing I did was transcribe")
    rem = find_repeats(ws, min_words=3, window_s=12)
    assert len(rem) == 1
    assert rem[0].text == "so the first thing I"
    assert rem[0].start == ws[0]["start"]
    assert rem[0].end == ws[5]["start"]  # cut ends where the second take begins


def test_single_word_stutter_is_removed():
    ws = words_from("I I think it works")
    rem = find_repeats(ws, min_words=3, window_s=12)
    assert len(rem) == 1 and rem[0].text == "I"


def test_repeat_outside_window_is_not_a_restart():
    ws = words_from("the pipeline is fast", start=0.0) + words_from("the pipeline is fast", start=30.0)
    assert find_repeats(ws, min_words=3, window_s=12) == []


def test_edges_trim_dead_air():
    ws = words_from("hello there", start=2.0)
    rem = find_edges(ws, duration=10.0)
    assert [r.reason for r in rem] == ["edges", "edges"]
    assert rem[0].end == 2.0 - 0.35
    assert rem[1].start == ws[-1]["end"] + 0.5


def test_merge_overlapping_removals_combines_reasons():
    from rawtoreel.cutlist import Removal

    merged = merge_removals([Removal(1, 2, "filler", "um"), Removal(1.5, 3, "silence", "pause"),
                             Removal(5, 6, "repeat", "x")], duration=10)
    assert [(r.start, r.end) for r in merged] == [(1, 3), (5, 6)]
    assert merged[0].reason == "filler+silence"


def test_complement_drops_tiny_keeps():
    from rawtoreel.cutlist import Removal

    keep = complement([Removal(1, 2, "x"), Removal(2.1, 5, "y")], duration=8, min_segment_s=0.4)
    assert keep == [(0.0, 1), (5, 8)]  # the 0.1 s sliver between removals is gone


def test_build_cutlist_never_returns_empty():
    cl = build_cutlist([], [(0, 5)], duration=5.0, settings=RoughCutSettings())
    assert cl.keep == [(0.0, 5.0)]


def test_build_cutlist_end_to_end_shortens():
    ws = words_from("hi um welcome to the the demo", start=1.0)
    silences = [(ws[-1]["end"], ws[-1]["end"] + 3.0)]
    cl = build_cutlist(ws, silences, duration=ws[-1]["end"] + 3.0)
    assert cl.duration_cut < cl.duration_raw
    reasons = {r.reason.split("+")[0] for r in cl.removed}
    assert {"filler", "repeat", "edges"} <= reasons
    assert cl.to_dict()["keep"]


def test_timemap_remaps_and_drops_removed_words():
    keep = [(0.0, 2.0), (5.0, 7.0)]
    tm = TimeMap(keep)
    assert tm.to_cut(1.0) == 1.0
    assert tm.to_cut(6.0) == 3.0
    assert tm.to_cut(3.5) is None
    ws = [{"w": "a", "start": 0.5, "end": 0.8}, {"w": "cut", "start": 3.0, "end": 3.4},
          {"w": "b", "start": 5.5, "end": 5.9}]
    out = tm.remap_words(ws)
    assert [w["w"] for w in out] == ["a", "b"]
    assert out[1]["start"] == 2.5
