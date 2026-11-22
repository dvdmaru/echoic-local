"""線上辨識逐段檢查與補轉、摘要缺段警告、頁首 STT 標示（2026-11-22 實例：第 2 段整段幻覺，摘要漏了一大段）。"""
import json
from pathlib import Path

import pytest

from meeting_local import cli, config, stt_api, summarize
from meeting_local.srt import Segment

AMARA = "整理&字幕由Amara.org社區提供"
CHUNKS = [(0.0, 614.0), (614.0, 1223.0), (1223.0, 1608.0)]  # 11/22 那場的切法


def _resp(texts, span):
    start, end = span
    step = (end - start) / len(texts)
    return {"text": "".join(texts),
            "segments": [{"start": i * step, "end": (i + 1) * step, "text": t} for i, t in enumerate(texts)]}


GOOD = [f"第 {i} 句正常的話" for i in range(20)]
BAD = [AMARA] * 77


@pytest.fixture
def fake_api(tmp_path: Path, monkeypatch):
    """bad_chunks：哪幾段（從 1 起算）線上回幻覺；redo_fixes：重試後會好的段。"""
    state = {"bad": set(), "redo_fixes": set(), "calls": []}

    def fake_cut(wav, start, end, dst):
        dst.write_bytes(b"x" * 10)
        return dst

    def fake_request(chunk, base, model, key, lang, prompt, temperature=0.0, **kw):
        i = int(chunk.name[6:8])
        state["calls"].append((i, prompt, temperature))
        redo = temperature > 0
        bad = i in state["bad"] and not (redo and i in state["redo_fixes"])
        return _resp(BAD if bad else GOOD, (0.0, CHUNKS[i - 1][1] - CHUNKS[i - 1][0]))

    monkeypatch.setattr(stt_api, "cut_flac", fake_cut)
    monkeypatch.setattr(stt_api, "request_chunk", fake_request)
    monkeypatch.setattr(stt_api, "plan_chunks_for", lambda wav, s: list(CHUNKS))
    return state


def run(tmp_path, repair=None):
    return stt_api.transcribe(tmp_path / "a.wav", tmp_path, "https://x/v1", "m", "k", "zh", None, split="chunk",
                              log=lambda s: None, local_repair=repair)


def test_bad_chunk_fixed_by_online_retry(tmp_path, fake_api):
    fake_api["bad"], fake_api["redo_fixes"] = {2}, {2}
    called = []
    segs, info = run(tmp_path, repair=lambda spans: called.append(spans))
    assert called == []  # 線上重試就好了，不動用本機
    assert [c for c in fake_api["calls"] if c[0] == 2] == [(2, None, 0.0), (2, None, stt_api.RETRY_TEMPERATURE)]
    assert not any(AMARA in s.text for s in segs)
    assert info["chunk_repairs"][0]["before"] == 1.0 and info["chunk_repairs"][0]["api_retry"] == 0.0
    assert info["local_repaired_chunks"] == 0
    assert (tmp_path / "stt-api" / "chunk-02.redo.json").exists()


def test_still_bad_chunk_goes_to_local_only_for_that_span(tmp_path, fake_api):
    fake_api["bad"] = {2}
    spans_seen = []

    def repair(spans):
        spans_seen.extend(spans)
        return [[Segment(s + 1, s + 5, "本機補回來的話"), Segment(s + 6, s + 9, "第二句")] for s, e in spans]

    segs, info = run(tmp_path, repair)
    assert spans_seen == [CHUNKS[1]]  # 只補壞的那 10 分鐘
    texts = [s.text for s in segs]
    assert AMARA not in texts and "本機補回來的話" in texts
    assert texts.count("第 0 句正常的話") == 2  # 第 1、3 段維持線上結果
    assert segs == sorted(segs, key=lambda s: s.start)
    assert info["local_repaired_chunks"] == 1 and info["chunk_repairs"][0]["local"] == 0.0


def test_most_chunks_bad_does_not_switch_whole_meeting_to_local(tmp_path, fake_api):
    fake_api["bad"] = {1, 2}  # 1223/1608 ≈ 76%：多半是語言選錯，交給整場失敗流程
    called = []
    segs, info = run(tmp_path, repair=lambda spans: called.append(spans))
    assert called == []
    assert info["local_repaired_chunks"] == 0
    assert sum(1 for s in segs if s.text == AMARA) == 154


def test_online_retry_error_does_not_fail_meeting(tmp_path, fake_api, monkeypatch):
    fake_api["bad"] = {2}
    first = stt_api.request_chunk

    def flaky(chunk, *a, temperature=0.0, **kw):
        if temperature > 0:
            raise stt_api.ApiError("線上語音辨識重試 4 次仍失敗")
        return first(chunk, *a, temperature=temperature, **kw)

    monkeypatch.setattr(stt_api, "request_chunk", flaky)
    seen = []
    segs, info = run(tmp_path, repair=lambda spans: seen.extend(spans) or [[Segment(700, 705, "補回")]])
    assert seen == [CHUNKS[1]] and "補回" in [s.text for s in segs]
    assert info["chunk_repairs"][0]["api_retry"] == 1.0


def test_local_repair_error_keeps_online_result(tmp_path, fake_api):
    fake_api["bad"] = {2}

    def boom(spans):
        raise RuntimeError("whisper-server 起不來")

    segs, info = run(tmp_path, boom)
    assert any(s.text == AMARA for s in segs)
    assert "起不來" in info["chunk_repairs"][0]["local_error"]


def test_transcribe_sends_no_glossary_online_but_repairs_with_full_local_prompt(tmp_path, monkeypatch):
    j = tmp_path / "2026-11-22-1108-test"
    j.mkdir()
    (j / "audio.wav").write_bytes(b"RIFF")
    gl = tmp_path / "glossary.md"
    gl.write_text("| 正確寫法 | 常見錯寫 |\n|---|---|\n| 輝達 | 揮達 |\n", encoding="utf-8")
    monkeypatch.setattr(config, "GLOSSARY", gl)
    monkeypatch.setattr(config, "SETTINGS_PATH", tmp_path / "settings.json")
    monkeypatch.setattr(cli, "probe", lambda p: {"duration": 100.0, "codec": "pcm_s16le", "sample_rate": 16000, "channels": 1})
    monkeypatch.setattr(cli, "_model_wav", lambda job, wav, args: (wav, {"mean_db": -30.0, "max_db": -1.0}))
    monkeypatch.setattr(cli, "_diarize_and_write", lambda *a, **k: None)
    seen = {}

    def api(job, wav, prompt, lang, local_repair=None):
        seen.update(prompt=prompt, repair_prompt=local_repair.prompt)
        return [Segment(0, 9, "正常的話")], {"engine": "api", "base_url_host": "api.example"}

    monkeypatch.setattr(cli, "_stt_api", api)
    assert cli.main(["transcribe", str(j), "--engine", "api"]) == 0
    assert seen["prompt"] is None
    assert "輝達" in seen["repair_prompt"]  # 本機補轉照舊帶完整提示
    stt = json.loads((j / "run.json").read_text(encoding="utf-8"))["models_touched"]["stt"]
    assert stt["prompt"] == ""


def test_stt_label_reads_actual_engine():
    assert summarize.stt_label({"engine": "whisper.cpp whisper-server (x)", "local": True,
                                "model": "/m/ggml-large-v3-turbo.bin"}) == "whisper.cpp large-v3-turbo（本機）"
    api = {"engine": "api", "base_url_host": "api.openai.com", "model": "whisper-1", "local": False}
    assert summarize.stt_label(api) == "whisper-1（線上 api.openai.com）"
    assert summarize.stt_label({**api, "local_repaired_chunks": 1}).endswith("其中 1 段改用本機補轉")
    assert summarize.stt_label(None) == "未記錄"


def test_missing_spans_and_notice():
    runs = [{"start": 614.0, "end": 1220.0}, {"start": 1215.0, "end": 1223.0}, {"start": 30.0, "end": 40.0}]
    spans = summarize.missing_spans(runs)
    assert spans == [(614.0, 1223.0)]  # 重疊併起來；10 秒的小迴圈不算缺段
    note = summarize.gap_notice(spans)
    assert note.startswith("> ⚠️") and "00:10:14–00:20:23" in note and "約 10 分鐘" in note
    assert summarize.gap_notice([]) == ""


def test_summary_puts_gap_warning_under_title_and_tells_model(monkeypatch):
    sent = {}

    def fake_claude(system, user, model=None):
        sent["user"] = user
        return "# 標題\n\n## 一句話\n內容"

    monkeypatch.setattr(summarize, "_claude", fake_claude)
    api = {"engine": "api", "base_url_host": "api.openai.com", "model": "whisper-1"}
    md, title = summarize.build_summary("x", "y", source="job", meeting_time="2026-11-22 11:08",
                                        stt=api, gaps=[(614.0, 1220.0)])
    lines = md.splitlines()
    assert "STT：whisper-1（線上 api.openai.com）" in lines[0]
    assert lines[2].startswith("# 標題") and lines[4].startswith("> ⚠️ **逐字稿缺段**")
    assert "## 逐字稿缺段" in sent["user"] and "00:10:14–00:20:20" in sent["user"]
    md2, _ = summarize.build_summary("x", "y", source="job", stt=api)
    assert "缺段" not in md2
