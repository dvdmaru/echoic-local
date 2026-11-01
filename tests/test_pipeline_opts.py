"""2026-10-05 回看三週會議後加的選項：與會者→人數、關 VAD＋max-context、限幅、摘要輸入。"""
import argparse
from pathlib import Path

from meeting_local import audio, cli, config, summarize
from meeting_local.whisper import WhisperServer


def test_parse_attendees_and_effective_speakers():
    assert cli.parse_attendees("Amy, David、小明；David") == ["Amy", "David", "小明"]
    assert cli.parse_attendees("") == [] and cli.parse_attendees(None) == []
    ns = argparse.Namespace(speakers=-1, attendees="A, B, C")
    assert cli._effective_speakers(ns) == 3
    ns = argparse.Namespace(speakers=2, attendees="A, B, C")
    assert cli._effective_speakers(ns) == 2  # 明給 --speakers 優先
    assert cli._effective_speakers(argparse.Namespace(speakers=-1, attendees=None)) == -1


def test_whisper_command_defaults_vad_off_with_max_context(tmp_path: Path):
    ws = WhisperServer(log_path=tmp_path / "w.log")
    cmd = ws.command()
    assert "--vad" not in cmd
    assert cmd[cmd.index("-mc") + 1] == "0"
    ws_vad = WhisperServer(log_path=tmp_path / "w.log", vad=True, max_context=None)
    cmd = ws_vad.command()
    assert "-mc" not in cmd
    assert ("--vad" in cmd) == config.VAD_MODEL.exists()


def test_record_cmd_has_limiter_and_input_volume(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(audio, "list_audio_devices", lambda: [(0, "BlackHole 2ch"), (1, "MacBook Air Microphone")])
    state = {"vol": 54}
    monkeypatch.setattr(audio, "input_volume", lambda: state["vol"])
    monkeypatch.setattr(audio, "set_input_volume", lambda level: state.__setitem__("vol", level) or True)
    cmd, info = audio.build_record_cmd(tmp_path / "a.wav", source="both", pipe_pcm=True)
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert "amix=inputs=2" in graph and config.LIMITER_FILTER in graph and graph.endswith("asplit=2[a][b]")
    assert info["mode"] == "mic+system"
    # 54 低於 85 → 開錄前自動拉到 85，before/after 都記下來（Teams／Zoom 會把系統輸入音量調低）
    assert (info["input_volume_before"], info["input_volume"], info["input_volume_changed"]) == (54, 85, True)
    assert "54 → 85" in audio.input_volume_note(info)
    cmd, info = audio.build_record_cmd(tmp_path / "a.wav", source="system")
    assert info["input_volume"] is None and audio.input_volume_note(info) is None  # 只錄系統音時輸入音量無關


def test_ensure_input_volume_rules(monkeypatch):
    # 已經 ≥ 目標：不動
    monkeypatch.setattr(audio, "input_volume", lambda: 90)
    monkeypatch.setattr(audio, "set_input_volume", lambda level: (_ for _ in ()).throw(AssertionError("不該呼叫")))
    assert audio.ensure_input_volume(85) == {"before": 90, "after": 90, "changed": False}
    # 目標 0＝關閉
    monkeypatch.setattr(audio, "input_volume", lambda: 30)
    assert audio.ensure_input_volume(0)["changed"] is False
    # 讀不到（非 macOS／沒權限）：不動也不炸
    monkeypatch.setattr(audio, "input_volume", lambda: None)
    assert audio.ensure_input_volume(85) == {"before": None, "after": None, "changed": False}
    # osascript 失敗：回報沒改，note 要警告手動拉
    monkeypatch.setattr(audio, "input_volume", lambda: 30)
    monkeypatch.setattr(audio, "set_input_volume", lambda level: False)
    r = audio.ensure_input_volume(85)
    assert r == {"before": 30, "after": 30, "changed": False}
    note = audio.input_volume_note({"input_volume": 30, "input_volume_before": 30, "input_volume_changed": False})
    assert note.startswith("⚠️") and "手動" in note
    # 門檻：偏小聲的尺現在是 -40（10/7、10/8 講話平均 -35／-37 不該再叫）
    assert config.LOW_LEVEL_DB == -40.0 and -35.0 > config.LOW_LEVEL_DB


def test_build_summary_input_includes_attendees_and_glossary():
    text = summarize.build_summary_input("逐字稿", "表", attendees=["Amy", "David"], glossary_md="| 正確寫法 |")
    assert text.index("## 與會者") < text.index("## 已確認詞彙表") < text.index("## 專名確認表") < text.index("## 逐字稿")
    assert "Amy、David" in text
    plain = summarize.build_summary_input("逐字稿", "表")
    assert "與會者" not in plain and "詞彙表" not in plain


def test_build_summary_header_mentions_attendees(monkeypatch):
    monkeypatch.setattr(summarize, "_claude", lambda *a, **k: "# 交接會議\n\n## 一句話\n測試\n")
    md, title = summarize.build_summary("x", "y", source="job", meeting_time="2026-10-05 11:45", attendees=["Amy"])
    assert title == "交接會議" and "與會者：Amy" in md.splitlines()[0]
