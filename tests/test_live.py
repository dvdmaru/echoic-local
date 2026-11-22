"""即時字幕（開會當下看；正式紀錄仍是會後轉錄）：邊錄邊切句、辨識＋翻譯、有沒有人問過、MCP 讀取。"""
import io
import json
import time
from pathlib import Path

import numpy as np
import pytest

from meeting_local import library, live, mcp_server, settings, stt_api
from meeting_local.recorder import Recorder
from test_mcp import call

SR = 16000


def audio(parts):
    rng = np.random.default_rng(0)
    out = []
    for sec, loud in parts:
        n = int(sec * SR)
        x = rng.normal(0, 0.002, n)
        if loud:
            x += 0.1 * np.sin(2 * np.pi * 220 * np.arange(n) / SR)
        out.append(x)
    return (np.concatenate(out) * 32767).astype(np.int16)


MEETING = [(4, False)] + [(3, True), (1.5, False)] * 5 + [(20, True), (2, False)]


def feed_all(sess_or_seg, pcm: bytes, step: int = 1600):
    got = []
    for off in range(0, len(pcm), step):
        r = sess_or_seg.feed(pcm[off:off + step])
        if r:
            got += r
    return got


def test_stream_segmenter_matches_batch_cutter():
    x = audio(MEETING)
    seg = live.StreamSegmenter()
    utts = feed_all(seg, x.tobytes()) + seg.flush()
    batch = stt_api.find_utterances(x, SR)
    assert len(utts) == len(batch) == 5 + 2  # 5 句＋20 秒連續講話切成 2 句（最長 12 秒）
    for (s, e, pcm), (bs, be) in zip(utts, batch):
        assert s == pytest.approx(bs, abs=0.35) and e == pytest.approx(be, abs=0.35)  # 下限門檻讓邊界差到 0.3 秒
        assert len(pcm) == pytest.approx((e - s) * SR * 2, rel=0.05)


def test_short_recording_still_flushes():
    seg = live.StreamSegmenter()
    x = audio([(0.3, False), (1.5, True), (0.2, False)])  # 不到 3 秒就停
    assert len(feed_all(seg, x.tobytes()) + seg.flush()) == 1


class FakeClaude:
    def __init__(self):
        self.translated, self.asked = [], []
        self.input_tokens = self.output_tokens = 0

    def translate(self, text, context, glossary=""):
        self.translated.append((text, list(context), glossary))
        return f"中文：{text}"

    def ask(self, question, transcript):
        self.asked.append((question, transcript))
        return "✅ 問過：00:00:04 有人問了"


def fake_request(texts):
    calls = []

    def req(path, base, model, key, lang, prompt, timeout=900, retries=4, **kw):
        k = int(path.stem[1:])  # 三個工作執行緒並行：照句子編號（u00003.wav）回，不照呼叫順序
        calls.append((path.name, lang, prompt, path.exists()))
        return {"text": texts[k] if k < len(texts) else f"sentence {k}"}

    return req, calls


def session(tmp_path, language="en", texts=(), claude=None):
    req, calls = fake_request(list(texts))
    job = tmp_path / "job"
    job.mkdir()
    s = live.LiveSession(job, language, stt_base="https://api.example/v1", stt_model="whisper-1", stt_key="k",
                         claude=claude if claude is not None else FakeClaude(), glossary="ROAS", request=req)
    s.start()
    return s, calls, job


def test_session_transcribes_translates_and_writes_jsonl(tmp_path):
    texts = ["Thanks for joining.", "What about the return rate?", "", "一二三四五六七八九十" * 22]
    s, calls, job = session(tmp_path, texts=texts)
    feed_all(s, audio(MEETING).tobytes())
    info = s.stop()
    assert len(calls) == 7 and all(c[1] == "en" and c[2] is None and c[3] for c in calls)  # 不帶提示、送的是 wav
    assert not list((job / ".live").glob("*.wav"))  # 送完就刪
    lines = s.changes(0)["lines"]
    status = {l["i"]: l["status"] for l in lines}
    assert status[2] == "skip" and status[3] == "skip"  # 空的、鬼打牆的不顯示
    done = [l for l in lines if l["status"] == "done"]
    assert done[0]["text"] == "Thanks for joining." and done[0]["zh"] == "中文：Thanks for joining."
    assert s.claude.translated[1][1] == ["Thanks for joining."]  # 前一句當上下文
    st, rows = live.read_live(job)
    assert st["active"] is False and st["translate"] == live.TRANSLATE_MODEL
    assert [r["text"] for r in rows][:2] == ["Thanks for joining.", "What about the return rate?"]
    assert info["lines"] == 5 and info["stt"]["host"] == "api.example"


def test_changes_are_incremental(tmp_path):
    s, _, _ = session(tmp_path)
    x = audio(MEETING).tobytes()
    feed_all(s, x[: len(x) // 2])
    deadline = time.time() + 5
    while s.changes(0)["pending"] and time.time() < deadline:
        time.sleep(0.05)
    first = s.changes(0)
    feed_all(s, x[len(x) // 2:])
    s.stop()
    later = s.changes(first["v"])
    assert later["v"] > first["v"] and later["lines"]
    assert {l["i"] for l in later["lines"]}.isdisjoint({l["i"] for l in first["lines"] if l["status"] == "done"})


def test_chinese_meeting_is_not_translated(tmp_path):
    claude = FakeClaude()
    s, _, _ = session(tmp_path, language="zh", texts=["我们开始吧"], claude=claude)
    feed_all(s, audio([(4, False), (3, True), (2, False)]).tobytes())
    s.stop()
    done = [l for l in s.changes(0)["lines"] if l["status"] == "done"]
    assert done[0]["text"] == "我們開始吧" and done[0]["zh"] == "" and claude.translated == []


def test_ask_uses_transcript_so_far(tmp_path):
    s, _, _ = session(tmp_path, texts=["What about the return rate?"])
    assert s.ask("有人問過退貨率嗎？").startswith("❌")  # 還沒有字幕
    feed_all(s, audio([(4, False), (3, True), (2, False)]).tobytes())
    s.stop()
    assert s.ask("有人問過退貨率嗎？").startswith("✅")
    q, transcript = s.claude.asked[0]
    assert q == "有人問過退貨率嗎？" and "What about the return rate?" in transcript and "[00:00:" in transcript


def test_one_failing_sentence_does_not_stop_the_rest(tmp_path):
    def req(path, *a, **kw):
        if path.name.endswith("00001.wav"):
            raise stt_api.ApiError("HTTP 500")
        return {"text": "fine"}

    job = tmp_path / "job"
    job.mkdir()
    s = live.LiveSession(job, "en", stt_base="https://x/v1", stt_model="m", stt_key="k", claude=FakeClaude(), request=req)
    s.start()
    feed_all(s, audio(MEETING).tobytes())
    s.stop()
    status = [l["status"] for l in s.changes(0)["lines"]]
    assert status.count("error") == 1 and status.count("done") == 6 and "HTTP 500" in s.error


def test_recorder_listener_errors_do_not_break_recording():
    rec = Recorder()
    got = []

    def bad(chunk):
        raise RuntimeError("boom")

    rec.listeners = [bad, got.append]

    class P:
        stdout = io.BytesIO(b"\x00\x01" * 4000)

    rec.proc = P()
    rec._read()
    assert sum(len(c) for c in got) == 8000 and rec._pow_n == 5


def test_readiness_lists_missing_keys(tmp_path, monkeypatch):
    monkeypatch.setattr(stt_api, "load_key", lambda path=None: None)
    monkeypatch.setattr(live, "load_anthropic_key", lambda: None)
    monkeypatch.setattr(live, "has_anthropic_login", lambda: False)
    missing = live.readiness("en")
    assert len(missing) == 2 and "Anthropic" in missing[1]


@pytest.fixture
def mcp_env(tmp_path):
    root = tmp_path / "meetings"
    sp = tmp_path / "settings.json"
    settings.save({"mcp_enabled": True, "mcp_transcripts": True}, sp)

    def meeting(name, labels, active=True, private=False):
        folder = root / name
        folder.mkdir(parents=True)
        library.write_meta(folder, labels=labels, private=private)
        (folder / live.LIVE_STATE).write_text(json.dumps({"active": active, "language": "en", "started_at": "x"}), encoding="utf-8")
        with open(folder / live.LIVE_LINES, "w", encoding="utf-8") as f:
            for i in range(5):
                f.write(json.dumps({"i": i, "t": f"00:00:0{i}", "text": f"line {i}", "zh": f"第 {i} 句"}) + "\n")
        return folder

    return mcp_server.Server(out_root=root, settings_path=sp, log_path=tmp_path / "log"), sp, meeting


def test_mcp_live_transcript_reads_incrementally(mcp_env):
    server, sp, meeting = mcp_env
    meeting("2026-11-23-1000-brand-hq", {"客戶": "甲公司"})
    err, r = call(server, "get_live_transcript")
    assert not err and r["active"] and r["total"] == 5 and r["next_since"] == 5 and r["lines"][0]["zh"] == "第 0 句"
    err, r2 = call(server, "get_live_transcript", {"since": 3})
    assert [l["i"] for l in r2["lines"]] == [3, 4]


def test_mcp_live_transcript_respects_scope_private_and_transcript_switch(mcp_env):
    server, sp, meeting = mcp_env
    meeting("2026-11-23-1000-a", {"客戶": "甲公司"}, private=True)
    meeting("2026-11-23-1100-b", {"客戶": "乙公司"})
    settings.save({"mcp_scope": {"客戶": ["甲公司"]}}, sp)
    err, r = call(server, "get_live_transcript")
    assert not err and r["meeting_id"] is None  # 甲公司那場標成不給、乙公司不在開放範圍
    settings.save({"mcp_scope": {}}, sp)
    err, r = call(server, "get_live_transcript")
    assert r["meeting_id"] == "2026-11-23-1100-b"
    settings.save({"mcp_transcripts": False}, sp)
    err, msg = call(server, "get_live_transcript")
    assert err and "逐字稿" in msg
    settings.save({"mcp_enabled": False, "mcp_transcripts": True}, sp)
    err, msg = call(server, "get_live_transcript")
    assert err  # 整個沒開就什麼都不給


def test_ui_has_live_controls():
    js = (Path(live.__file__).parent / "web" / "app.js").read_text(encoding="utf-8")
    for marker in ("rLive", "live_ask", "save_anthropic_key", "renderCaps", "live: wantLive", "正式紀錄仍是會後整場轉錄"):
        assert marker in js, marker
