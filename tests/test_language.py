"""會議語言：錄音時選、重轉時可改，記在該場 run.json（2026-11-20 英文 ZEISS 會議被指定成中文、線上辨識 87% 幻覺）。"""
import json
from argparse import Namespace
from pathlib import Path

import pytest

from meeting_local import cli, config, settings, webapp
from meeting_local.srt import Segment


@pytest.fixture
def job(tmp_path: Path, monkeypatch):
    j = tmp_path / "2026-11-20-1601-test"
    j.mkdir()
    (j / "audio.wav").write_bytes(b"RIFF")
    monkeypatch.setattr(config, "GLOSSARY", tmp_path / "glossary.md")
    monkeypatch.setattr(config, "SETTINGS_PATH", tmp_path / "settings.json")
    monkeypatch.setattr(cli, "probe", lambda p: {"duration": 100.0, "codec": "pcm_s16le", "sample_rate": 16000, "channels": 1})
    monkeypatch.setattr(cli, "_model_wav", lambda job, wav, args: (wav, {"mean_db": -30.0, "max_db": -1.0}))
    monkeypatch.setattr(cli, "_diarize_and_write", lambda *a, **k: None)
    seen = {}
    good = [Segment(i * 10.0, i * 10.0 + 9.0, f"Sentence number {i} is fine.") for i in range(10)]

    def local(job, wav, prompt, args, lang):
        seen.update(engine="local", prompt=prompt, lang=lang)
        return good, {"engine": "whisper.cpp", "local": True}

    def api(job, wav, prompt, lang):
        seen.update(engine="api", prompt=prompt, lang=lang)
        return good, {"engine": "api", "base_url_host": "api.example"}

    monkeypatch.setattr(cli, "_stt_local", local)
    monkeypatch.setattr(cli, "_stt_api", api)
    return j, seen


def run_json(j: Path) -> dict:
    return json.loads((j / "run.json").read_text(encoding="utf-8"))


def test_language_precedence(tmp_path: Path):
    rj = tmp_path / "run.json"
    assert cli.meeting_language(Namespace(language=None), rj) == config.WHISPER_LANGUAGE  # 沒檔＝預設
    rj.write_text(json.dumps({"language": "en"}), encoding="utf-8")
    assert cli.meeting_language(Namespace(language=None), rj) == "en"  # 這場記的
    assert cli.meeting_language(Namespace(language="zh"), rj) == "zh"  # 旗標最優先
    rj.write_text(json.dumps({"language": "klingon"}), encoding="utf-8")
    assert cli.meeting_language(Namespace(), rj) == config.WHISPER_LANGUAGE  # 不認得的值不照用


def test_english_meeting_uses_english_prompt_and_sticks(job):
    j, seen = job
    (j / "run.json").write_text(json.dumps({"language": "en"}), encoding="utf-8")  # 錄音時選了英文
    assert cli.main(["transcribe", str(j), "--engine", "local"]) == 0
    assert seen["lang"] == "en"
    assert seen["prompt"].startswith(config.DEFAULT_PROMPTS["en"]) and "繁體" not in seen["prompt"]
    assert run_json(j)["language"] == "en"


def test_language_flag_overrides_and_is_remembered(job):
    j, seen = job
    assert cli.main(["transcribe", str(j), "--engine", "api", "--language", "en"]) == 0
    assert seen == {**seen, "engine": "api", "lang": "en"}
    assert run_json(j)["language"] == "en"
    assert cli.main(["transcribe", str(j), "--engine", "local"]) == 0  # 下次沒給旗標＝沿用這場
    assert seen["lang"] == "en"


def test_default_stays_chinese(job):
    j, seen = job
    assert cli.main(["transcribe", str(j), "--engine", "local"]) == 0
    assert seen["lang"] == "zh" and seen["prompt"].startswith(config.DEFAULT_PROMPT)


def test_record_and_all_accept_language():
    p = cli.build_parser()
    assert p.parse_args(["record", "--language", "en"]).language == "en"
    assert p.parse_args(["all", "x", "--language", "zh"]).language == "zh"
    with pytest.raises(SystemExit):
        p.parse_args(["transcribe", "x", "--language", "fr"])


def test_webapp_rerun_passes_language_and_get_meeting_reports_it(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings.config, "SETTINGS_PATH", tmp_path / "settings.json")
    monkeypatch.setattr(settings.config, "STT_API_KEY_PATH", tmp_path / "stt-api-key")
    root = tmp_path / "meetings"
    from test_library import make
    m = make(root, "2026-11-20-1601-英文會議", "英文會議")
    api = webapp.Api(root)
    argvs = []
    monkeypatch.setattr(api, "_run_cli", lambda argv: argvs.append(argv) or 0)
    monkeypatch.setattr(api, "_start", lambda name, job, fn: fn())

    assert api.get_meeting(m.name)["language"] == config.WHISPER_LANGUAGE
    api.run_pipeline(m.name, None, "", "local", "en")
    assert argvs[-1][argvs[-1].index("--language") + 1] == "en"
    api.run_pipeline(m.name, None, "", "local", "fr")  # 不認得的語言不傳，交給這場記的／預設
    assert "--language" not in argvs[-1]

    (m / "run.json").write_text(json.dumps({"language": "en"}), encoding="utf-8")
    assert api.get_meeting(m.name)["language"] == "en"


def test_record_screen_offers_language():
    js = (Path(webapp.__file__).parent / "web" / "app.js").read_text(encoding="utf-8")
    assert "language: R.language" in js and "rerunDialog(m, 'local')" in js
