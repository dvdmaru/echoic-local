"""App 內更新：版本比較、Release 解析、SHA、換版腳本、（本機有 dmg 時）下載到換版前一步的端到端。"""
import functools
import http.server
import json
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from meeting_local import config, settings, updater

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"


def test_version_compare():
    assert updater.newer("0.4.1", "0.4.0") and updater.newer("v0.10.0", "0.9.9")
    assert not updater.newer("0.4.0", "0.4.0") and not updater.newer("0.3.9", "0.4.0")
    assert updater.parse_version("v1.2.3") == (1, 2, 3)


def test_expected_sha():
    good = "a" * 64
    text = f"{good}  {updater.DMG}\n{'b' * 64}  other.dmg\n"
    assert updater.expected_sha(text) == good
    assert updater.expected_sha(f"{good}  *{updater.DMG}\n") == good  # shasum -b 的寫法
    assert updater.expected_sha("not-a-sha  " + updater.DMG) is None


def test_due_once_a_day():
    now = 1_000_000.0
    assert updater.due(0, now) and updater.due(now - updater.CHECK_EVERY, now)
    assert not updater.due(now - 3600, now)


def _fake_curl(payload):
    def run(cmd, capture_output=True, stdin=None):
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload).encode(), stderr=b"")
    return run


def test_latest_release_reads_assets():
    rel = updater.latest_release(run=_fake_curl({
        "tag_name": "v0.5.0", "html_url": "https://x/rel",
        "assets": [{"name": updater.DMG, "browser_download_url": "https://x/dmg"},
                   {"name": updater.SUMS, "browser_download_url": "https://x/sums"}]}))
    assert rel == {"version": "0.5.0", "dmg": "https://x/dmg", "sums": "https://x/sums", "page": "https://x/rel"}


def test_latest_release_without_checksums_refuses():
    with pytest.raises(RuntimeError, match="SHA256SUMS"):
        updater.latest_release(run=_fake_curl({"tag_name": "v9.9.9", "assets": [
            {"name": updater.DMG, "browser_download_url": "https://x/dmg"}]}))


def test_source_checkout_has_no_bundle(monkeypatch):
    monkeypatch.setattr(config, "FROZEN", False)
    assert updater.app_bundle() is None


def test_frozen_app_finds_its_bundle(monkeypatch, tmp_path):
    exe = tmp_path / "Applications" / "Echoic 本機版.app" / "Contents" / "MacOS" / "Echoic 本機版"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    monkeypatch.setattr(config, "FROZEN", True)
    monkeypatch.setattr(sys, "executable", str(exe))
    assert updater.app_bundle() == tmp_path / "Applications" / "Echoic 本機版.app"
    assert updater.staged_path(updater.app_bundle()).parent == tmp_path / "Applications"  # 新版放舊版旁邊、同一個磁碟才能 mv


def test_settings_update_keys(tmp_path):
    p = tmp_path / "s.json"
    s = settings.load(p)
    assert s["update_check"] is True and s["update_checked_at"] == 0.0
    p.write_text(json.dumps({"update_check": "no", "update_checked_at": -5}), encoding="utf-8")
    s = settings.load(p)
    assert s["update_check"] is True and s["update_checked_at"] == 0.0
    settings.save({"update_check": False, "update_checked_at": 123.5}, p)
    s = settings.load(p)
    assert s["update_check"] is False and s["update_checked_at"] == 123.5


@pytest.mark.skipif(sys.platform != "darwin", reason="換版腳本用 macOS 的 open")
def test_swap_script_replaces_old_after_app_exits(tmp_path):
    old = tmp_path / "Echoic 本機版.app"
    new = tmp_path / ".echoic-local-update.app"
    (old / "Contents").mkdir(parents=True)
    (old / "Contents" / "v").write_text("old")
    (new / "Contents").mkdir(parents=True)
    (new / "Contents" / "v").write_text("new")
    app = subprocess.Popen(["sleep", "1"])  # 假裝是正在跑的舊版 App
    script = updater.launch_swap(old, new, pid=app.pid, reopen=False)
    assert (old / "Contents" / "v").read_text() == "old"  # App 還沒結束前不准動
    app.wait()
    for _ in range(40):
        if not new.exists() and not script.exists():
            break
        time.sleep(0.25)
    assert (old / "Contents" / "v").read_text() == "new"
    assert not new.exists() and not script.exists()  # 換完自己清乾淨


_DMG = DIST / updater.DMG


@pytest.mark.skipif(not (_DMG.exists() and (DIST / updater.SUMS).exists() and shutil.which("hdiutil")),
                    reason="本機沒有打包好的 dmg（CI）")
def test_prepare_downloads_verifies_and_stages(tmp_path):
    h = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(DIST))
    h.log_message = lambda *a: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), h)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        bundle = tmp_path / "Echoic 本機版.app"
        bundle.mkdir()
        rel = {"version": "test", "dmg": f"{base}/{updater.DMG}", "sums": f"{base}/{updater.SUMS}", "page": base}
        new = updater.prepare(rel, bundle, log=lambda t: None)
        assert new == updater.staged_path(bundle) and (new / "Contents" / "Info.plist").exists()
        q = subprocess.run(["xattr", "-p", "com.apple.quarantine", str(new)], capture_output=True)
        assert q.returncode != 0  # 沒有隔離標記＝打開時不會被 Gatekeeper 擋
        shutil.rmtree(new)

        missing = dict(rel, sums=f"{base}/does-not-exist.txt")
        with pytest.raises(RuntimeError, match="連不上"):
            updater.prepare(missing, bundle, log=lambda t: None)
        assert not updater.staged_path(bundle).exists()

        wrong_dir = tmp_path / "wrong"
        wrong_dir.mkdir()
        (wrong_dir / updater.SUMS).write_text("0" * 64 + f"  {updater.DMG}\n")
        h2 = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(wrong_dir))
        h2.log_message = lambda *a: None
        srv2 = http.server.ThreadingHTTPServer(("127.0.0.1", 0), h2)
        threading.Thread(target=srv2.serve_forever, daemon=True).start()
        try:
            wrong = dict(rel, sums=f"http://127.0.0.1:{srv2.server_address[1]}/{updater.SUMS}")
            with pytest.raises(RuntimeError, match="SHA-256 不符"):
                updater.prepare(wrong, bundle, log=lambda t: None)
            assert not updater.staged_path(bundle).exists() and bundle.exists()  # 舊版沒動、沒有半套新版
        finally:
            srv2.shutdown()
    finally:
        srv.shutdown()
