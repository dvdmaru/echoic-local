from meeting_local.dedup import collapse_hallucinations, flag_suspects, normalize
from meeting_local.srt import Segment


def seg(i, text):
    return Segment(start=float(i), end=float(i) + 1.0, text=text)


def test_normalize_ignores_punct_space_case():
    assert normalize("我 昨天，超過。") == normalize("我昨天超過")
    assert normalize("PowerPoint!") == "powerpoint"


def test_run_of_102_collapses_to_one():
    segs = [seg(0, "開場")] + [seg(i, "我昨天超過房間時期") for i in range(1, 103)] + [seg(200, "結尾")]
    out, report = collapse_hallucinations(segs)
    assert len(out) == 3
    mid = out[1]
    assert mid.flag == "hallucination"
    assert mid.start == 1.0 and mid.end == 103.0
    assert "×102" in mid.text and "[幻覺，已略]" in mid.text
    assert report[0]["repeats"] == 102


def test_run_of_2_kept():
    segs = [seg(0, "同一句"), seg(1, "同一句"), seg(2, "別句")]
    out, report = collapse_hallucinations(segs)
    assert len(out) == 3 and report == []


def test_exactly_min_run_collapses():
    segs = [seg(i, "重複") for i in range(3)]
    out, _ = collapse_hallucinations(segs, min_run=3)
    assert len(out) == 1


def test_alternating_kept():
    segs = [seg(i, "A" if i % 2 else "B") for i in range(10)]
    out, report = collapse_hallucinations(segs)
    assert len(out) == 10 and report == []


def test_empty_text_never_collapses():
    segs = [seg(i, "") for i in range(5)]
    out, report = collapse_hallucinations(segs)
    assert len(out) == 5 and report == []


def test_suspect_flag_keeps_text():
    segs = [seg(0, "字幕由 Amara.org 社群提供"), seg(1, "我們訂閱制的收入")]
    hits = flag_suspects(segs)
    assert len(hits) == 1 and segs[0].flag == "suspect" and segs[1].flag is None
