"""背景模式與線上語音辨識的端到端：whisper 指令、分離子程序、假的 OpenAI 相容伺服器。

需要真實元件的測試（分離模型、ffmpeg）在缺件時略過：CI 是 Ubuntu、沒有這些。"""
import argparse
import http.server
import json
import shutil
import threading
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from meeting_local import cli, config, settings, stt_api
from meeting_local.whisper import WhisperServer


def test_whisper_threads_and_background_command(tmp_path: Path):
    fast = WhisperServer(log_path=tmp_path / "w.log")
    assert fast.threads == config.WHISPER_THREADS == 4  # 8 → 4：實測不變慢、前景不再被搶
    assert fast.command()[0] != "/usr/bin/nice"
    bg = WhisperServer(log_path=tmp_path / "w.log", background=True)
    cmd = bg.command()
    assert cmd[:3] == ["/usr/bin/nice", "-n", str(config.BACKGROUND_NICE)]
    assert cmd[cmd.index("-t") + 1] == str(config.WHISPER_THREADS_BACKGROUND)
    assert "taskpolicy" not in " ".join(cmd)  # 背景 QoS 實測讓前景更慢，不用
    assert "-ng" not in cmd  # 純 CPU 實測慢 7.5 倍，背景模式也用 GPU


def test_speed_flag_beats_setting(monkeypatch):
    monkeypatch.setattr(settings, "load", lambda path=None: {**settings.DEFAULTS, "local_speed": "background"})
    assert cli.local_speed(argparse.Namespace(speed=None)) == "background"
    assert cli.local_speed(argparse.Namespace(speed="fast")) == "fast"
    assert set(cli.SPEED_LABELS) == set(settings.LOCAL_SPEEDS) == set(cli.SPEED_HINTS)


_MODELS = config.MODELS_DIR / config.SEG_MODEL_DIRNAME / "model.onnx"


@pytest.mark.skipif(not _MODELS.exists(), reason="沒有說話人分離模型（CI）")
def test_diarize_runs_in_child_process_and_reports_progress(tmp_path: Path):
    from meeting_local.diarize import diarize_isolated

    sr = 16000
    t = np.arange(sr * 8) / sr
    audio = (0.3 * np.sin(2 * np.pi * 180 * t) * (np.sin(2 * np.pi * 0.5 * t) > 0)).astype(np.float32)
    wav = tmp_path / "a.wav"
    sf.write(wav, audio, sr, subtype="PCM_16")
    lines = []
    result = diarize_isolated(wav, num_speakers=1, threshold=1.1, num_threads=1, nice=5, log=lines.append)
    assert isinstance(result, list)
    assert all(set(r) == {"start", "end", "speaker"} for r in result)
    assert any("說話人分離" in ln for ln in lines)


@pytest.mark.skipif(not _MODELS.exists(), reason="沒有說話人分離模型（CI）")
def test_diarize_child_error_comes_back(tmp_path: Path):
    from meeting_local.diarize import diarize_isolated

    wav = tmp_path / "a.wav"
    sf.write(wav, np.zeros(8000, dtype=np.float32), 8000)  # 8 kHz：子程序會拒絕
    with pytest.raises(RuntimeError, match="16 kHz"):
        diarize_isolated(wav, num_threads=1)


class _FakeOpenAI(http.server.BaseHTTPRequestHandler):
    seen: list = []

    def do_POST(self):  # noqa: N802
        body = self.rfile.read(int(self.headers["Content-Length"]))
        type(self).seen.append({"path": self.path, "auth": self.headers.get("Authorization"),
                                "has_file": b'name="file"' in body, "model": b"whisper-test" in body})
        out = json.dumps({"text": "大家好", "segments": [{"start": 0.5, "end": 2.0, "text": "大家好"},
                                                         {"start": 2.5, "end": 4.0, "text": "开始开会"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


@pytest.mark.skipif(not Path(config.FFMPEG).exists() or not shutil.which("curl"), reason="沒有 ffmpeg／curl（CI）")
def test_api_engine_end_to_end_with_fake_server(tmp_path: Path, monkeypatch):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _FakeOpenAI)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    _FakeOpenAI.seen = []
    try:
        base = f"http://127.0.0.1:{srv.server_address[1]}/v1"
        monkeypatch.setattr(config, "SETTINGS_PATH", tmp_path / "cfg" / "settings.json")
        monkeypatch.setattr(config, "STT_API_KEY_PATH", tmp_path / "cfg" / "stt-api-key")
        monkeypatch.setattr(config, "GLOSSARY", tmp_path / "詞彙表.md")
        monkeypatch.setattr(config, "TW_GATE", tmp_path / "no-gate.py")
        monkeypatch.delenv("MEETING_LOCAL_STT_API_KEY", raising=False)
        settings.save({"stt_engine": "api", "stt_api_base_url": base, "stt_api_model": "whisper-test"})
        stt_api.save_key("sk-fake-123")
        sr = 16000
        wav = tmp_path / "in.wav"
        sf.write(wav, (0.1 * np.sin(2 * np.pi * 220 * np.arange(sr * 5) / sr)).astype(np.float32), sr, subtype="PCM_16")
        rc = cli.main(["transcribe", str(wav), "--out", str(tmp_path / "out"), "--name", "job", "--no-diarize"])
        assert rc == 0
        job = tmp_path / "out" / "job"
        assert _FakeOpenAI.seen == [{"path": "/v1/audio/transcriptions", "auth": "Bearer sk-fake-123",
                                     "has_file": True, "model": True}]
        srt = (job / "transcript.srt").read_text(encoding="utf-8")
        assert "大家好" in srt and "開始開會" in srt  # 線上回的簡體也走同一條轉正體
        run = json.loads((job / "run.json").read_text(encoding="utf-8"))
        stt = run["models_touched"]["stt"]
        assert stt["engine"] == "api" and stt["local"] is False and stt["base_url_host"].startswith("127.0.0.1")
        assert "sk-fake" not in json.dumps(run)  # key 不進 run.json
        assert not list((job / "stt-api").glob("*.flac"))  # 切片傳完就刪
    finally:
        srv.shutdown()
