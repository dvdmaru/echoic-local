"""線上語音辨識整段幻覺時要停下來、標失敗，讓畫面提供「用本機重轉」（2026-11-19 potatopost 實例）。"""
import json
from pathlib import Path

import pytest

from meeting_local import cli, config
from meeting_local.srt import Segment


def test_coverage_merges_overlaps_and_clips():
    assert cli.hallucination_coverage([], 100) == 0.0
    assert cli.hallucination_coverage([{"start": 0, "end": 10}], 0) == 0.0
    runs = [{"start": 0, "end": 30}, {"start": 20, "end": 50}, {"start": 90, "end": 200}]
    assert cli.hallucination_coverage(runs, 100) == pytest.approx(0.6)  # 0–50 ＋ 90–100
    # 11/19 實例的形狀：兩組迴圈蓋滿、尾巴超過音檔長度
    assert cli.hallucination_coverage([{"start": 0, "end": 56}, {"start": 56, "end": 756}], 734.1) == 1.0


@pytest.fixture
def job(tmp_path: Path, monkeypatch):
    j = tmp_path / "2026-11-19-1500-test"
    j.mkdir()
    (j / "audio.wav").write_bytes(b"RIFF")
    monkeypatch.setattr(config, "GLOSSARY", tmp_path / "glossary.md")
    monkeypatch.setattr(config, "SETTINGS_PATH", tmp_path / "settings.json")
    monkeypatch.setattr(cli, "probe", lambda p: {"duration": 100.0, "codec": "pcm_s16le", "sample_rate": 16000, "channels": 1})
    monkeypatch.setattr(cli, "_model_wav", lambda job, wav, args: (wav, {"mean_db": -30.0, "max_db": -1.0}))
    written = []
    monkeypatch.setattr(cli, "_diarize_and_write", lambda job, wav, segs, halluc, args, model_wav=None: written.append(len(segs)))
    return j, written


def run_json(j: Path) -> dict:
    return json.loads((j / "run.json").read_text(encoding="utf-8"))


def test_api_hallucination_stops_then_local_clears(job, monkeypatch):
    j, written = job
    loop = [Segment(i * 2.0, i * 2.0 + 2.0, "咳") for i in range(50)]
    monkeypatch.setattr(cli, "_stt_api", lambda job, wav, prompt: (loop, {"engine": "api", "base_url_host": "api.example"}))

    rc = cli.main(["transcribe", str(j), "--engine", "api"])
    assert rc == cli.STT_FAILED
    assert written == []  # 幻覺沒有寫成逐字稿
    d = run_json(j)
    assert d["stt_failed"]["engine"] == "api" and d["stt_failed"]["host"] == "api.example"
    assert d["stt_failed"]["coverage"] == pytest.approx(1.0)

    good = [Segment(i * 10.0, i * 10.0 + 9.0, f"第 {i} 句正常的話") for i in range(10)]
    monkeypatch.setattr(cli, "_stt_local", lambda job, wav, prompt, args: (good, {"engine": "whisper.cpp", "local": True}))
    rc = cli.main(["transcribe", str(j), "--engine", "local"])
    assert rc == 0
    assert written == [10]
    assert run_json(j)["stt_failed"] is None


def test_partial_loss_flag_for_meeting_page():
    from meeting_local.webapp import Api

    api = {"engine": "api"}
    # 舊 run.json 沒有 coverage 欄位：用幻覺紀錄現算（11/11 Meteor 的形狀：1164 秒裡 10:30–19:08 是迴圈）
    old = {"audio": {"duration": 1164.0}, "hallucination_runs": [{"start": 541, "end": 555}, {"start": 630, "end": 1148}]}
    assert Api._partial_loss(old, api) == pytest.approx(0.457, abs=0.002)
    assert Api._partial_loss({"hallucination_coverage": 0.1}, api) is None  # 太少不吵
    assert Api._partial_loss({"hallucination_coverage": 0.9}, api) is None  # 那是「失敗」，另一個框
    assert Api._partial_loss({"hallucination_coverage": 0.3}, {"engine": "whisper.cpp"}) is None  # 本機轉的不提示改本機
    assert Api._partial_loss({"hallucination_coverage": 0.3, "stt_failed": {"engine": "api"}}, api) is None


def test_partial_hallucination_on_api_still_transcribes(job, monkeypatch):
    j, written = job
    segs = [Segment(i * 2.0, i * 2.0 + 2.0, "咳") for i in range(10)]  # 0–20 秒迴圈＝20%
    segs += [Segment(20.0 + i * 8.0, 28.0 + i * 8.0, f"內容 {i}") for i in range(10)]
    monkeypatch.setattr(cli, "_stt_api", lambda job, wav, prompt: (segs, {"engine": "api", "base_url_host": "api.example"}))
    assert cli.main(["transcribe", str(j), "--engine", "api"]) == 0
    assert written and run_json(j)["stt_failed"] is None
