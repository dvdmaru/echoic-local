from meeting_local.diarize import assign_speakers, minor_speakers, talk_time


def test_minor_speakers_absorbed():
    diar = [
        {"start": 0, "end": 50, "speaker": "SPEAKER_00"},
        {"start": 50, "end": 50.5, "speaker": "SPEAKER_07"},  # 0.5s 咳嗽
        {"start": 50.5, "end": 100, "speaker": "SPEAKER_01"},
    ]
    minor = minor_speakers(diar, min_share=0.02)
    assert minor == {"SPEAKER_07"}
    segs = [Segment(49.8, 50.4, "嗯")]
    assign_speakers(segs, diar, ignore=minor)
    assert segs[0].speaker == "SPEAKER_00"  # 0.2s 重疊 SPEAKER_00 勝出，零碎群被忽略
    assert "SPEAKER_07" not in talk_time(diar, ignore=minor)
from meeting_local.outputs import by_minute_text
from meeting_local.srt import Segment


def test_assign_by_overlap_and_carry():
    segs = [Segment(0, 2, "a"), Segment(2, 4, "b"), Segment(10, 11, "c"), Segment(20, 25, "[幻覺，已略] x", flag="hallucination")]
    diar = [
        {"start": 0, "end": 1.5, "speaker": "SPEAKER_00"},
        {"start": 1.5, "end": 5, "speaker": "SPEAKER_01"},
    ]
    assign_speakers(segs, diar)
    assert segs[0].speaker == "SPEAKER_00"  # 1.5s vs 0.5s
    assert segs[1].speaker == "SPEAKER_01"
    assert segs[2].speaker == "SPEAKER_01"  # 沒重疊 → 沿用上一段
    assert segs[3].speaker is None
    assert talk_time(diar) == {"SPEAKER_00": 1.5, "SPEAKER_01": 3.5}


def test_by_minute_groups_and_merges():
    segs = [
        Segment(0, 1, "早安", speaker="SPEAKER_00"),
        Segment(1, 2, "開始", speaker="SPEAKER_00"),
        Segment(2, 3, "好", speaker="SPEAKER_01"),
        Segment(61, 62, "第二分鐘", speaker="SPEAKER_01"),
        Segment(70, 80, "[幻覺，已略] 「x」×5", flag="hallucination"),
    ]
    report = [{"start": 70, "end": 80, "start_clock": "00:01:10", "end_clock": "00:01:20", "text": "x", "repeats": 5}]
    txt = by_minute_text(segs, "audio.wav", report)
    assert "## 00:00" in txt and "## 00:01" in txt
    assert "[00:00:00] SPEAKER_00：早安 開始" in txt
    assert "[00:00:02] SPEAKER_01：好" in txt
    assert "⚠️ [00:01:10–00:01:20] [幻覺，已略]" in txt
    assert "「x」×5" in txt
