import argparse

from meeting_local import cli, settings


def test_auto_summary_defaults_off(tmp_path):
    p = tmp_path / "s.json"
    assert settings.auto_summary(p) is False  # 沒設定檔＝關：摘要會用到使用者自己的 Claude 額度
    p.write_text("{壞掉的 json", encoding="utf-8")
    assert settings.auto_summary(p) is False


def test_save_roundtrip_keeps_only_known_keys(tmp_path):
    p = tmp_path / "sub" / "s.json"
    settings.save({"auto_summary": True, "unknown": 1}, p)
    assert settings.auto_summary(p) is True
    assert "unknown" not in p.read_text(encoding="utf-8")
    settings.save({"auto_summary": False}, p)
    assert settings.auto_summary(p) is False


def test_cost_note_mentions_own_quota_and_opt_out():
    note = settings.SUMMARY_COST_NOTE
    assert "你自己 Claude 方案的用量" in note and "US$20" in note and "只出逐字稿" in note


def test_want_summary_flag_beats_setting(monkeypatch):
    monkeypatch.setattr(settings, "auto_summary", lambda path=None: True)
    assert cli.want_summary(argparse.Namespace(summary=None)) is True
    assert cli.want_summary(argparse.Namespace(summary=False)) is False
    monkeypatch.setattr(settings, "auto_summary", lambda path=None: False)
    assert cli.want_summary(argparse.Namespace(summary=None)) is False
    assert cli.want_summary(argparse.Namespace(summary=True)) is True


def test_all_parser_summary_flags():
    p = cli.build_parser()
    assert p.parse_args(["all", "x.wav"]).summary is None
    assert p.parse_args(["all", "x.wav", "--summary"]).summary is True
    assert p.parse_args(["all", "x.wav", "--no-summary"]).summary is False
    assert p.parse_args(["config", "--auto-summary", "on"]).func is cli.cmd_config


def _fake_pipeline(monkeypatch, tmp_path, calls):
    job = tmp_path / "2026-11-01-1200"
    job.mkdir()
    monkeypatch.setattr(cli, "cmd_transcribe", lambda a: job)
    monkeypatch.setattr(cli, "cmd_entities", lambda a: calls.append("entities"))
    monkeypatch.setattr(cli, "cmd_summarize", lambda a: calls.append("summarize") or job)
    return job


def test_all_skips_summary_when_off(monkeypatch, tmp_path):
    calls = []
    job = _fake_pipeline(monkeypatch, tmp_path, calls)
    args = argparse.Namespace(path=str(job), summary=False)
    assert cli.cmd_all(args) == job and calls == []


def test_all_without_claude_returns_summary_failed(monkeypatch, tmp_path):
    calls = []
    job = _fake_pipeline(monkeypatch, tmp_path, calls)
    monkeypatch.setattr(cli.config, "claude_available", lambda: False)
    assert cli.cmd_all(argparse.Namespace(path=str(job), summary=True)) == cli.SUMMARY_FAILED and calls == []


def test_all_summary_error_keeps_transcript(monkeypatch, tmp_path):
    calls = []
    job = _fake_pipeline(monkeypatch, tmp_path, calls)
    monkeypatch.setattr(cli.config, "claude_available", lambda: True)

    def boom(a):
        raise RuntimeError("claude CLI 未登入")
    monkeypatch.setattr(cli, "cmd_entities", boom)
    assert cli.cmd_all(argparse.Namespace(path=str(job), summary=True)) == cli.SUMMARY_FAILED


def test_all_with_summary(monkeypatch, tmp_path):
    calls = []
    job = _fake_pipeline(monkeypatch, tmp_path, calls)
    monkeypatch.setattr(cli.config, "claude_available", lambda: True)
    assert cli.cmd_all(argparse.Namespace(path=str(job), summary=True)) == job
    assert calls == ["entities", "summarize"]
