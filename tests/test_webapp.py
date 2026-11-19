import http.client
import threading
from pathlib import Path

import pytest

from meeting_local import library, settings, webapp
from test_library import make


@pytest.fixture
def env(tmp_path: Path, monkeypatch):
    root = tmp_path / "meetings"
    a = make(root, "2026-10-01-1000-官網啟動", "官網啟動會", labels={"客戶": "甲公司", "專案": "官網"})
    make(root, "2026-10-15-1400-官網進度", "官網進度會", labels={"客戶": "甲公司", "專案": "官網"})
    make(root, "2026-10-20-0900-乙公司提案", "乙公司提案", labels={"客戶": "乙公司"})
    (a / "audio.wav").write_bytes(bytes(range(256)) * 40)  # 10240 bytes 假音檔
    (a / "提案.html").write_text("<h1>提案</h1><script>alert(1)</script>", encoding="utf-8")
    monkeypatch.setattr(settings.config, "SETTINGS_PATH", tmp_path / "settings.json")
    monkeypatch.setattr(settings.config, "STT_API_KEY_PATH", tmp_path / "stt-api-key")  # 別讀到這台電腦真的 key
    return webapp.Api(root), root


def test_api_exposes_no_public_attributes(env):
    api, _ = env
    public = [k for k in vars(api) if not k.startswith("_")]
    assert public == []  # pywebview 會把公開屬性整個暴露給網頁


def test_poll_carries_download_progress_and_clears_when_done(env):
    import time
    api, _ = env
    gate = threading.Event()

    def work():
        api._bytes("下載 9.9.9")(25, 100)
        gate.wait(5)
        return {"ok": True}

    api._start("update", "", work)
    for _ in range(100):
        if api.poll(0)["progress"]:
            break
        time.sleep(0.01)
    assert api.poll(0)["progress"] == {"label": "下載 9.9.9", "done": 25, "total": 100}
    gate.set()
    for _ in range(100):
        if not api.poll(0)["busy"]:
            break
        time.sleep(0.01)
    assert api.poll(0)["progress"] is None

def test_record_source_defaults_to_both_when_blackhole_present():
    # 0.7.0 把預設寫死成只錄麥克風，線上會議對方的聲音只剩喇叭回授，線上辨識整段幻覺（2026-11-19）。
    js = (Path(webapp.__file__).parent / "web" / "app.js").read_text(encoding="utf-8")
    assert "source: 'mic'" not in js
    assert "v === 'both' && ok" in js


def test_tree_and_list(env):
    api, _ = env
    t = api.tree()
    assert t["top"] == "客戶" and t["sub"] == "專案" and t["total"] == 3
    assert t["groups"][0] == {"value": "甲公司", "count": 2, "children": [{"value": "官網", "count": 2}]}
    res = api.list_meetings({"labels": {"客戶": "甲公司"}, "query": "十二月"})
    assert res["total"] == 2 and res["meetings"][0]["hits"]


def test_get_meeting_has_context_and_transcript(env):
    api, _ = env
    m = api.get_meeting("2026-10-15-1400-官網進度")
    assert m["ok"] and m["summary_html"].startswith("<h2>一句話</h2>")
    assert m["transcript"][0]["speaker"] == "SPEAKER_00" and m["transcript"][0]["sec"] == 190
    ctx = m["context"]
    assert ctx["labels"] == {"客戶": "甲公司", "專案": "官網"}
    assert ctx["last"]["id"] == "2026-10-01-1000-官網啟動"
    assert len(ctx["open_todos"]) == 2
    assert api.get_meeting("nope")["ok"] is False


def test_set_todo_writes_summary_and_index_matches(env):
    api, root = env
    m = library.find(library.load_meetings(root), "2026-10-01-1000-官網啟動")
    assert [t.index for t in m.todos] == [0, 1]
    assert api.set_todo(m.id, 0, True)["ok"]
    m2 = library.find(library.load_meetings(root), m.id)
    assert m2.todos[0].done is True
    assert "- [x] 寄報價單" in m2.summary_text()


def test_set_labels_refreshes_threads(env):
    api, root = env
    assert api.set_labels(["2026-10-20-0900-乙公司提案"], {"專案": "年度廣告"})["ok"]
    assert library.read_meta(root / "2026-10-20-0900-乙公司提案")["labels"] == {"客戶": "乙公司", "專案": "年度廣告"}
    assert {"客戶": "乙公司", "專案": "年度廣告"} in library.existing_threads(root)


def test_read_file_blocks_traversal(env):
    api, _ = env
    assert api.read_file("2026-10-01-1000-官網啟動", "../2026-10-20-0900-乙公司提案/summary.md")["ok"] is False
    r = api.read_file("2026-10-01-1000-官網啟動", "提案.html")
    assert r["kind"] == "html" and "<script>" in r["text"]  # 原樣給前端，前端放 sandbox iframe


def test_save_settings_whitelist(env):
    api, _ = env
    r = api.save_settings({"mcp_enabled": True, "stt_api_base_url": "https://evil.example"})
    assert r["ok"] and r["settings"]["mcp_enabled"] is True
    assert r["settings"]["stt_api_base_url"] != "https://evil.example"  # 只准走 save_api
    assert api.save_settings({"stt_engine": "api"})["ok"] is False  # 沒 key 不能切線上
    assert api.save_settings({"categories": []})["ok"] is False


def test_notes_append_with_timestamp(env, monkeypatch):
    api, root = env
    job = root / "2026-11-01-1000"
    job.mkdir()
    api._rec.job = job
    monkeypatch.setattr(api._rec, "elapsed", lambda: 3725.4)
    assert api.add_note("預算要確認含不含稅") == {"ok": True, "t": "01:02:05"}
    assert api.notes("2026-11-01-1000") == [{"t": "01:02:05", "text": "預算要確認含不含稅"}]


def test_summary_input_includes_notes():
    from meeting_local.summarize import build_summary_input
    text = build_summary_input("逐字稿", "專名", notes_md="- [00:01:00] 預算含稅？")
    assert "會議中的手記" in text and "預算含稅" in text
    assert "手記" not in build_summary_input("逐字稿", "專名")


@pytest.fixture
def server(env):
    api, root = env
    srv = webapp.make_server(api, "tok123")
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    yield srv.server_address[1]
    srv.shutdown()


def get(port, path, headers=None, host=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    h = {"Host": host or f"127.0.0.1:{port}", **(headers or {})}
    c.request("GET", path, headers=h)
    r = c.getresponse()
    return r.status, dict(r.getheaders()), r.read()


def test_server_token_host_and_files(server):
    port = server
    assert get(port, "/tok123/")[0] == 200
    st, hd, body = get(port, "/tok123/app.js")
    assert st == 200 and hd["Content-Type"].startswith("text/javascript")
    assert get(port, "/wrong/")[0] == 403
    assert get(port, "/tok123/", host="evil.example:80")[0] == 403  # DNS rebinding
    assert get(port, "/tok123/../pyproject.toml")[0] in (403, 404)
    assert "Content-Security-Policy" in get(port, "/tok123/index.html")[1]


def test_server_media_range_and_only_audio(server):
    port = server
    mid = "2026-10-01-1000-%E5%AE%98%E7%B6%B2%E5%95%9F%E5%8B%95"
    st, hd, body = get(port, f"/tok123/media/{mid}/audio.wav", {"Range": "bytes=100-199"})
    assert st == 206 and hd["Content-Range"] == "bytes 100-199/10240" and len(body) == 100 and body[0] == 100
    st, _, body = get(port, f"/tok123/media/{mid}/audio.wav")
    assert st == 200 and len(body) == 10240
    assert get(port, f"/tok123/media/{mid}/summary.md")[0] == 404  # 只給錄音檔
    assert get(port, f"/tok123/media/{mid}/..%2F..%2Fsettings.json")[0] == 404
