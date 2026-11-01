from meeting_local.srt import parse_srt
from meeting_local.whisper import decode_whisper_output


def _srt(a: bytes, b: bytes) -> bytes:
    return (b"1\n00:00:01,000 --> 00:00:02,000\n" + a +
            b"\n\n2\n00:00:02,000 --> 00:00:03,000\n" + b + b"\n")


def test_clean_passthrough():
    raw = _srt("你好".encode(), "再見".encode())
    text, repaired, dropped = decode_whisper_output(raw)
    assert text == raw.decode()
    assert (repaired, dropped) == (0, 0)


def test_char_split_across_segments_is_joined():
    zhong = "中".encode()  # e4 b8 ad
    raw = _srt("我們".encode() + zhong[:1], zhong[1:] + "午見".encode())
    text, repaired, dropped = decode_whisper_output(raw)
    assert (repaired, dropped) == (1, 0)
    segs = parse_srt(text)
    assert [s.text for s in segs] == ["我們", "中午見"]


def test_split_after_two_bytes():
    zhong = "中".encode()
    raw = _srt("我們".encode() + zhong[:2], zhong[2:] + "午".encode())
    text, repaired, _ = decode_whisper_output(raw)
    assert repaired == 1
    assert [s.text for s in parse_srt(text)] == ["我們", "中午"]


def test_orphan_byte_dropped_not_fatal():
    # 0x91 單獨出現（本次 10/28 實際炸掉的 byte）：接不回就丟掉，不讓整份失敗
    raw = _srt("我們".encode() + b"\x91", "好".encode())
    text, repaired, dropped = decode_whisper_output(raw)
    assert repaired == 0 and dropped == 1
    assert [s.text for s in parse_srt(text)] == ["我們", "好"]


def test_mid_segment_missing_bytes():
    # 10/28 實際的兩種形狀：兩字中間夾孤立 continuation bytes；lead＋1 byte 後直接接英文
    zhong = "中".encode()
    raw = _srt("我".encode() + b"\x91\xa5" + "們".encode(), "好".encode() + zhong[:2] + b"resolve")
    text, repaired, dropped = decode_whisper_output(raw)
    assert repaired == 0 and dropped == 3
    assert [s.text for s in parse_srt(text)] == ["我們", "好resolve"]
