"""線上語音辨識（使用者自選）：切段、時間軸、key 不外露、重試規則、設定驗證。全部不連網。"""
import argparse
import json
import stat
import subprocess
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from meeting_local import cli, settings, stt_api


def test_short_audio_is_one_chunk():
    assert stt_api.plan_chunks(300.0) == [(0.0, 300.0)]
    assert stt_api.plan_chunks(900.0) == [(0.0, 900.0)]  # 不到 1.5 段就不切，少打一次 API


def test_chunks_cover_everything_and_tail_merges():
    chunks = stt_api.plan_chunks(9074.0)  # 151 分鐘的會議
    assert chunks[0][0] == 0.0 and chunks[-1][1] == 9074.0
    assert all(a[1] == b[0] for a, b in zip(chunks, chunks[1:]))  # 首尾相接，沒有漏也沒有重疊
    assert all(e - s <= stt_api.CHUNK_SECONDS * 1.5 for s, e in chunks)
    assert 9074.0 - chunks[-1][0] >= stt_api.CHUNK_SECONDS * 0.5  # 尾巴太短會併進前一段


def test_cut_lands_on_the_quiet_spot(tmp_path: Path):
    sr = 16000
    rng = np.random.default_rng(0)
    audio = (rng.standard_normal(sr * 1300) * 0.2).astype(np.float32)
    quiet = int(608 * sr)  # 第 608 秒有 1 秒靜音：切點要落在這裡，不是硬切在 600
    audio[quiet:quiet + sr] = 0
    wav = tmp_path / "a.wav"
    sf.write(wav, audio, sr, subtype="PCM_16")
    chunks = stt_api.plan_chunks_for(wav)
    assert 608.0 <= chunks[0][1] <= 609.0


def test_segments_offset_and_clamped():
    resp = {"segments": [{"start": 1.0, "end": 3.0, "text": " 你好 "}, {"start": 598.0, "end": 605.0, "text": "跨界"},
                         {"start": 4, "end": 5, "text": "  "}]}
    segs = stt_api.segments_from_response(resp, offset=600.0, chunk_end=1200.0)
    assert [(s.start, s.end, s.text) for s in segs] == [(601.0, 603.0, "你好"), (1198.0, 1200.0, "跨界")]
    only_text = stt_api.segments_from_response({"text": "整段"}, offset=0.0, chunk_end=30.0)
    assert [(s.start, s.end, s.text) for s in only_text] == [(0.0, 30.0, "整段")]


def test_key_never_in_command_line(tmp_path: Path):
    cmd = stt_api.curl_command(tmp_path / "c.flac", "https://api.example.com/v1/", "whisper-1", "zh", "詞彙：甲", 60)
    joined = " ".join(cmd)
    assert "Bearer" not in joined and "@-" in cmd  # key 走 stdin
    assert cmd[-1] == "https://api.example.com/v1/audio/transcriptions"
    assert "response_format=verbose_json" in cmd and "language=zh" in cmd


def _fake_run(responses, seen):
    def run(cmd, input=None, capture_output=True):
        seen.append(input)
        body, code, rc = responses.pop(0)
        return subprocess.CompletedProcess(cmd, rc, stdout=f"{body}\n{code}".encode(), stderr=b"")
    return run


def test_request_sends_key_on_stdin_and_parses(tmp_path: Path):
    seen = []
    run = _fake_run([(json.dumps({"segments": []}), 200, 0)], seen)
    out = stt_api.request_chunk(tmp_path / "c.flac", "https://x/v1", "m", "sk-test", "zh", None, run=run, sleep=lambda s: None)
    assert out == {"segments": []}
    assert seen == [b"Authorization: Bearer sk-test\n"]


def test_request_retries_rate_limit_then_succeeds(tmp_path: Path):
    sleeps = []
    run = _fake_run([('{"error":{"message":"slow down"}}', 429, 0), ("", 0, 7), ('{"text":"ok"}', 200, 0)], [])
    out = stt_api.request_chunk(tmp_path / "c.flac", "https://x/v1", "m", "k", "zh", None, run=run, sleep=sleeps.append)
    assert out == {"text": "ok"} and len(sleeps) == 2


def test_request_bad_key_fails_fast(tmp_path: Path):
    sleeps = []
    run = _fake_run([('{"error":{"message":"Incorrect API key"}}', 401, 0)], [])
    with pytest.raises(stt_api.ApiError, match="API key 被拒絕"):
        stt_api.request_chunk(tmp_path / "c.flac", "https://x/v1", "m", "k", "zh", None, run=run, sleep=sleeps.append)
    assert sleeps == []  # 401 重試也沒用


def test_request_gives_up_after_retries(tmp_path: Path):
    run = _fake_run([("", 503, 0)] * (stt_api.RETRIES + 1), [])
    with pytest.raises(stt_api.ApiError, match="重試"):
        stt_api.request_chunk(tmp_path / "c.flac", "https://x/v1", "m", "k", "zh", None, run=run, sleep=lambda s: None)


def test_key_file_is_private_and_clearable(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("MEETING_LOCAL_STT_API_KEY", raising=False)
    p = tmp_path / "cfg" / "stt-api-key"
    stt_api.save_key("  sk-abc  \n", p)
    assert stat.S_IMODE(p.stat().st_mode) == 0o600
    assert stt_api.load_key(p) == "sk-abc"
    with pytest.raises(ValueError):
        stt_api.save_key("a\nb", p)
    stt_api.save_key("", p)
    assert not p.exists() and stt_api.load_key(p) is None


def test_settings_validate_engine_and_defaults(tmp_path: Path):
    p = tmp_path / "s.json"
    s = settings.load(p)
    assert s["stt_engine"] == "local" and s["local_speed"] == "fast"  # 沒設定＝本機、錄音不出電腦
    p.write_text(json.dumps({"stt_engine": "cloud", "stt_api_model": "", "auto_summary": "yes"}), encoding="utf-8")
    s = settings.load(p)
    assert s["stt_engine"] == "local" and s["stt_api_model"] == stt_api.DEFAULT_MODEL and s["auto_summary"] is False
    settings.save({"stt_engine": "api", "stt_api_base_url": "https://api.groq.com/openai/v1"}, p)
    assert settings.load(p)["stt_engine"] == "api"
    assert "key" not in p.read_text(encoding="utf-8").lower().replace("stt_api_", "")


def test_engine_flag_beats_setting(monkeypatch):
    monkeypatch.setattr(settings, "load", lambda path=None: {**settings.DEFAULTS, "stt_engine": "api"})
    assert cli.stt_engine(argparse.Namespace(engine=None)) == "api"
    assert cli.stt_engine(argparse.Namespace(engine="local")) == "local"
    p = cli.build_parser()
    assert p.parse_args(["all", "x.wav", "--engine", "api"]).engine == "api"
    assert p.parse_args(["transcribe", "x.wav"]).engine is None


def test_api_without_key_says_how_to_fix(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(stt_api, "load_key", lambda path=None: None)
    with pytest.raises(RuntimeError, match="還沒填 API key"):
        cli._stt_api(tmp_path, tmp_path / "a.wav", "")


def test_warning_names_the_host():
    w = stt_api.warning("https://api.groq.com/openai/v1")
    assert "api.groq.com" in w and "上傳" in w and "公司或客戶的會議" in w
