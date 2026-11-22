"""線上辨識一句一句送（2026-11-22 起預設）：切句、單句重試、長段幻覺改本機補、一句內鬼打牆。"""
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from meeting_local import stt_api
from meeting_local.dedup import collapse_hallucinations, inner_loop
from meeting_local.srt import Segment

SR = 16000
LOOP = "一二三四五六七八九十" * 22  # 11/22 實例：7 秒的話回成這樣
AMARA = "整理&字幕由Amara.org社區提供"


def audio(parts):
    """parts：[(秒數, 是否有聲)]；有聲＝0.1 振幅的 220 Hz，安靜＝很小的底噪。"""
    rng = np.random.default_rng(0)
    out = []
    for sec, loud in parts:
        n = int(sec * SR)
        x = rng.normal(0, 0.002, n)
        if loud:
            x += 0.1 * np.sin(2 * np.pi * 220 * np.arange(n) / SR)
        out.append(x)
    return np.concatenate(out).astype(np.float32)


def test_find_utterances_cuts_on_silence_and_caps_length():
    x = audio([(1, False), (1.5, True), (2, False), (3, True), (1, False), (0.1, True), (1, False), (30, True), (1, False)])
    utts = stt_api.find_utterances(x, SR)
    assert utts[0][0] == pytest.approx(1.0 - stt_api.PREROLL, abs=0.05)
    assert utts[0][1] - utts[0][0] == pytest.approx(0.3 + 1.5 + 0.7, abs=0.1)
    assert all(e - s <= stt_api.MAX_UTTERANCE + 0.05 for s, e in utts)
    # 0.1 秒的「喀」不送；30 秒連續講話切成 3 句
    assert len(utts) == 2 + 3
    assert sum(e - s for s, e in utts) < len(x) / SR  # 安靜的時間不送


def test_steady_audio_is_not_thrown_away():
    # 音量一直很平（全程有聲、沒有停頓）：門檻不能高過說話聲
    utts = stt_api.find_utterances(audio([(20, True)]), SR)
    assert sum(e - s for s, e in utts) >= 19.0


def test_find_utterances_int16_matches_float():
    x = audio([(1, False), (2, True), (1, False)])
    assert stt_api.find_utterances((x * 32767).astype(np.int16), SR) == stt_api.find_utterances(x, SR)


def test_inner_loop_detects_counting_loop_only():
    assert inner_loop(LOOP)
    assert not inner_loop("對對對對對")  # 短的不算
    assert not inner_loop("我們今天先把這一張照片換掉，然後旁白第三段的人名要改成正確的寫法")
    out, report = collapse_hallucinations([Segment(0, 5, "開場"), Segment(5, 12, LOOP), Segment(12, 15, "結尾")])
    assert [s.flag for s in out] == [None, "hallucination", None]
    assert report[0]["inner"] and report[0]["start"] == 5


@pytest.fixture
def meeting(tmp_path: Path):
    # 句子：每句 4 秒有聲＋1.5 秒安靜，共 40 句（約 3.7 分鐘）
    wav = tmp_path / "a.wav"
    sf.write(str(wav), audio([(1, False)] + [(4, True), (1.5, False)] * 40), SR, subtype="PCM_16")
    return wav


def fake_api(monkeypatch, answer):
    calls = []

    def fake_request(chunk, base, model, key, lang, prompt, temperature=0.0, **kw):
        k = int(chunk.stem.split("-")[1])
        calls.append((k, prompt, temperature))
        dur = sf.info(str(chunk)).duration
        text = answer(k, temperature)
        return {"text": text, "segments": [{"start": 0.0, "end": dur, "text": text}]}

    monkeypatch.setattr(stt_api, "request_chunk", fake_request)
    return calls


def run(wav, repair=None):
    return stt_api.transcribe(wav, wav.parent, "https://x/v1", "m", "k", "zh", None, log=lambda s: None,
                              local_repair=repair)


def test_default_is_sentence_split_and_files_are_cleaned(meeting, monkeypatch):
    calls = fake_api(monkeypatch, lambda k, t: f"第 {k} 句")
    segs, info = run(meeting)
    assert info["split"] == "sentence" and info["utterances"] == 40 == len(calls)
    assert [s.text for s in segs] == [f"第 {k} 句" for k in range(40)]
    assert segs == sorted(segs, key=lambda s: s.start)
    assert info["voiced_seconds"] < 40 * 5.5  # 安靜的時間沒送
    assert not list((meeting.parent / "stt-api").glob("utt-*.wav"))
    assert len((meeting.parent / "stt-api" / "responses.jsonl").read_text(encoding="utf-8").splitlines()) == 40


def test_bad_sentence_is_retried_once_with_new_temperature(meeting, monkeypatch):
    calls = fake_api(monkeypatch, lambda k, t: LOOP if (k == 7 and t == 0) else f"第 {k} 句")
    segs, info = run(meeting)
    assert [c for c in calls if c[0] == 7] == [(7, None, 0.0), (7, None, stt_api.RETRY_TEMPERATURE)]
    assert "第 7 句" in [s.text for s in segs] and LOOP not in [s.text for s in segs]
    assert info["utterance_retries"] == 1 and info["requests"] == 41


def test_long_bad_stretch_goes_to_local_only_for_that_span(meeting, monkeypatch):
    fake_api(monkeypatch, lambda k, t: AMARA if 10 <= k < 25 else f"第 {k} 句")  # 約 80 秒連續亂回
    spans_seen = []

    def repair(spans):
        spans_seen.extend(spans)
        return [[Segment(s + 1, s + 3, "本機補回來的話")] for s, e in spans]

    segs, info = run(meeting, repair)
    assert len(spans_seen) == 1 and spans_seen[0][1] - spans_seen[0][0] >= stt_api.GAP_REPAIR_SECONDS
    texts = [s.text for s in segs]
    assert AMARA not in texts and "本機補回來的話" in texts and "第 9 句" in texts and "第 25 句" in texts
    assert info["local_repaired_chunks"] == 1


def test_short_bad_stretch_is_not_sent_to_local(meeting, monkeypatch):
    fake_api(monkeypatch, lambda k, t: AMARA if 10 <= k < 13 else f"第 {k} 句")  # 3 句、十幾秒
    called = []
    segs, info = run(meeting, repair=lambda spans: called.append(spans))
    assert called == [] and "local_repairs" not in info


def test_mostly_bad_meeting_is_left_to_whole_meeting_failure(meeting, monkeypatch):
    fake_api(monkeypatch, lambda k, t: AMARA)
    called = []
    segs, info = run(meeting, repair=lambda spans: called.append(spans))
    assert called == []  # 交給 cli 的整場失敗流程，不在背景整場改本機


def test_silent_recording_raises_readable_error(tmp_path, monkeypatch):
    wav = tmp_path / "a.wav"
    sf.write(str(wav), np.zeros(SR * 3, dtype=np.float32), SR, subtype="PCM_16")
    fake_api(monkeypatch, lambda k, t: "不該被呼叫")
    with pytest.raises(stt_api.ApiError, match="偵測不到有人講話"):
        run(wav)
