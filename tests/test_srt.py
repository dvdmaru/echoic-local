from meeting_local.srt import Segment, fmt_clock, fmt_srt_ts, parse_srt, render_srt

SAMPLE = """1
00:00:01,000 --> 00:00:03,500
你好

2
00:01:02,250 --> 00:01:04,000
第二段
第二行
"""


def test_parse():
    segs = parse_srt(SAMPLE)
    assert len(segs) == 2
    assert segs[0].start == 1.0 and segs[0].end == 3.5 and segs[0].text == "你好"
    assert segs[1].start == 62.25 and segs[1].text == "第二段 第二行"


def test_parse_accepts_dot_millis_and_crlf():
    segs = parse_srt("1\r\n00:00:00.5 --> 00:00:01.0\r\nx\r\n")
    assert segs[0].start == 0.5 and segs[0].end == 1.0


def test_roundtrip_with_speaker():
    segs = [Segment(1.0, 3.5, "你好", speaker="SPEAKER_00")]
    out = render_srt(segs)
    assert "[SPEAKER_00] 你好" in out
    back = parse_srt(out)
    assert back[0].start == 1.0 and back[0].end == 3.5


def test_fmt():
    assert fmt_srt_ts(3661.0) == "01:01:01,000"
    assert fmt_srt_ts(0.9995) == "00:00:01,000"
    assert fmt_clock(3599.9) == "00:59:59"
