import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from meeting_local import library, mcp_server, settings
from test_library import make


@pytest.fixture
def env(tmp_path: Path):
    root = tmp_path / "meetings"
    make(root, "2026-10-01-1000-官網啟動", "官網啟動會", labels={"客戶": "甲公司", "專案": "官網"})
    make(root, "2026-10-20-0900-乙公司提案", "乙公司提案", labels={"客戶": "乙公司"})
    secret = make(root, "2026-10-25-0900-人事", "人事會議", labels={"客戶": "甲公司"})
    library.write_meta(secret, private=True)
    sp = tmp_path / "settings.json"
    settings.save({"mcp_enabled": True}, sp)
    log = tmp_path / "access.log"
    return mcp_server.Server(out_root=root, settings_path=sp, log_path=log), sp, log


def rpc(server, method, params=None, mid=1):
    return server.handle({"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}})


def call(server, name, args=None):
    res = rpc(server, "tools/call", {"name": name, "arguments": args or {}})["result"]
    return res["isError"], (res["content"][0]["text"] if res["isError"] else json.loads(res["content"][0]["text"]))


def test_initialize_and_tools_list(env):
    server, _, _ = env
    init = rpc(server, "initialize", {"protocolVersion": "2025-03-26", "clientInfo": {"name": "claude-ai"}})["result"]
    assert init["protocolVersion"] == "2025-03-26"
    assert "instructions" in init and init["capabilities"] == {"tools": {"listChanged": False}}
    assert rpc(server, "initialize", {"protocolVersion": "1999-01-01"})["result"]["protocolVersion"] == "2025-06-18"
    tools = rpc(server, "tools/list")["result"]["tools"]
    assert {t["name"] for t in tools} == {"list_categories", "list_meetings", "search_meetings", "get_meeting",
                                          "get_transcript", "get_project_thread", "list_open_todos"}
    assert all(t["annotations"]["readOnlyHint"] for t in tools)
    assert server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert rpc(server, "nope")["error"]["code"] == -32601


def test_disabled_returns_friendly_error(env):
    server, sp, _ = env
    settings.save({"mcp_enabled": False}, sp)
    err, text = call(server, "list_meetings")
    assert err and "AI 助理連線" in text


def test_private_meetings_are_invisible(env):
    server, _, _ = env
    _, data = call(server, "list_meetings")
    ids = [m["id"] for m in data["meetings"]]
    assert "2026-10-25-0900-人事" not in ids and len(ids) == 2
    err, _ = call(server, "get_meeting", {"meeting_id": "2026-10-25-0900-人事"})
    assert err
    _, data = call(server, "search_meetings", {"query": "人事"})
    assert data["total"] == 0


def test_scope_limits_to_selected_values(env):
    server, sp, _ = env
    settings.save({"mcp_scope": {"客戶": ["乙公司"]}}, sp)
    _, data = call(server, "list_meetings")
    assert [m["id"] for m in data["meetings"]] == ["2026-10-20-0900-乙公司提案"]
    _, cats = call(server, "list_categories")
    assert cats["values"]["客戶"] == {"乙公司": 1}


def test_transcripts_can_be_withheld(env):
    server, sp, _ = env
    _, data = call(server, "get_transcript", {"meeting_id": "2026-10-01-1000-官網啟動", "max_chars": 1000})
    assert "十二月" in data["text"] and data["next_offset"] is None
    settings.save({"mcp_transcripts": False}, sp)
    err, text = call(server, "get_transcript", {"meeting_id": "2026-10-01-1000-官網啟動"})
    assert err and "不開放逐字稿" in text
    _, res = call(server, "search_meetings", {"query": "十二月"})
    assert res["total"] == 0  # 只出現在逐字稿的詞搜不到


def test_get_meeting_and_thread_and_todos(env):
    server, _, _ = env
    _, m = call(server, "get_meeting", {"meeting_id": "2026-10-01-1000-官網啟動"})
    assert "## 決議" in m["summary_markdown"] and "<!--" not in m["summary_markdown"]
    assert m["todos"][0]["owner"] == "Charlie"
    _, th = call(server, "get_project_thread", {"labels": {"客戶": "甲公司"}})
    assert [x["id"] for x in th["meetings"]] == ["2026-10-01-1000-官網啟動"]  # 人事那場被排除
    assert th["ai_report"] is None
    _, todos = call(server, "list_open_todos", {"labels": {"客戶": "乙公司"}})
    assert todos["total"] == 1 and todos["todos"][0]["labels"] == {"客戶": "乙公司"}


def test_thread_ai_report_hidden_if_it_used_out_of_scope_meetings(env):
    server, sp, _ = env
    root = server.out_root
    labels = {"客戶": "甲公司"}
    all_ms = library.filter_meetings(library.load_meetings(root), labels)  # 含 private 那場
    library.write_thread(root, labels, all_ms, ai_report="### 目前進度\n- 人事調整（10/25 人事會議）")
    _, th = call(server, "get_project_thread", {"labels": labels})
    assert th["ai_report"] is None  # 整理時讀過不給看的會議，不能經由報告外流


def test_access_log_records_client_and_ids(env):
    server, _, log = env
    rpc(server, "initialize", {"clientInfo": {"name": "claude-code"}})
    call(server, "get_meeting", {"meeting_id": "2026-10-01-1000-官網啟動"})
    rec = json.loads(log.read_text(encoding="utf-8").splitlines()[-1])
    assert rec["client"] == "claude-code" and rec["tool"] == "get_meeting"
    assert rec["meetings"] == ["2026-10-01-1000-官網啟動"]


def test_serve_over_stdio_bytes(env):
    server, _, _ = env
    lines = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "list_categories", "arguments": {}}},
    ]
    stdin = io.BytesIO(("\n".join(json.dumps(l, ensure_ascii=False) for l in lines) + "\nnot json\n").encode())
    stdout = io.BytesIO()
    server.serve(stdin, stdout)
    out = [json.loads(l) for l in stdout.getvalue().decode().splitlines()]
    assert [o.get("id") for o in out] == [1, 2, None]
    assert out[2]["error"]["code"] == -32700
    assert json.loads(out[1]["result"]["content"][0]["text"])["meetings"] == 2


def test_cli_mcp_subprocess(env, tmp_path: Path):
    server, sp, _ = env
    msgs = "\n".join(json.dumps(m) for m in [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "list_meetings", "arguments": {"limit": 1}}},
    ]) + "\n"
    env_vars = {"MEETING_LOCAL_SETTINGS": str(sp), "PATH": "/usr/bin:/bin", "HOME": str(tmp_path)}
    proc = subprocess.run([sys.executable, "-m", "meeting_local.cli", "mcp", "--out", str(server.out_root)],
                          input=msgs.encode(), capture_output=True, timeout=60, env=env_vars,
                          cwd=Path(__file__).resolve().parents[1])
    out = [json.loads(l) for l in proc.stdout.decode().splitlines()]
    assert proc.returncode == 0, proc.stderr.decode()
    assert json.loads(out[1]["result"]["content"][0]["text"])["returned"] == 1
