import json
import os
import subprocess
import time

import pytest

from meeting_local import cli, joblock


def _write(job, pid, ts=None, step="transcribe"):
    (job / joblock.LOCK_NAME).write_text(json.dumps({
        "pid": pid, "ts": ts if ts is not None else time.time(), "started": "2026-10-28 13:06:16", "step": step,
    }))


def _dead_pid():
    p = subprocess.Popen(["true"])
    p.wait()
    return p.pid


def test_same_pid_reacquire_and_release(tmp_path):
    joblock.acquire(tmp_path, "transcribe")
    joblock.acquire(tmp_path, "summarize")  # all 串下去不會被自己擋
    assert json.loads((tmp_path / joblock.LOCK_NAME).read_text())["step"] == "summarize"
    joblock.release_all()
    assert not (tmp_path / joblock.LOCK_NAME).exists()


def test_other_live_pid_blocks(tmp_path):
    _write(tmp_path, os.getppid())
    with pytest.raises(RuntimeError, match=r"pid \d+.*13:06:16.*transcribe"):
        joblock.acquire(tmp_path, "transcribe")


def test_dead_pid_is_stale(tmp_path):
    _write(tmp_path, _dead_pid())
    joblock.acquire(tmp_path, "transcribe")
    assert json.loads((tmp_path / joblock.LOCK_NAME).read_text())["pid"] == os.getpid()
    joblock.release_all()


def test_old_lock_is_stale(tmp_path):
    _write(tmp_path, os.getppid(), ts=time.time() - joblock.STALE_SECONDS - 1)
    joblock.acquire(tmp_path, "transcribe")
    joblock.release_all()


def test_release_leaves_others_lock(tmp_path):
    joblock.acquire(tmp_path, "transcribe")
    _write(tmp_path, os.getppid())  # 被別人接手覆寫
    joblock.release_all()
    assert (tmp_path / joblock.LOCK_NAME).exists()


def test_main_releases_on_error(tmp_path):
    # summarize 拿到鎖後因缺檔失敗，main() 回 1 且鎖已放掉
    assert cli.main(["summarize", str(tmp_path)]) == 1
    assert not (tmp_path / joblock.LOCK_NAME).exists()


def test_main_reports_busy(tmp_path, capsys):
    _write(tmp_path, os.getppid(), step="transcribe")
    assert cli.main(["diarize", str(tmp_path)]) == 1
    assert "正在被另一個 meeting-local 處理" in capsys.readouterr().err
    assert (tmp_path / joblock.LOCK_NAME).exists()  # 別人的鎖不動


def test_moved_releases_at_new_path(tmp_path):
    old, new = tmp_path / "2026-11-05-1200", tmp_path / "2026-11-05-1200-標題"
    old.mkdir()
    joblock.acquire(old, "summarize")
    old.rename(new)
    joblock.moved(old, new)
    joblock.release_all()
    assert not (new / joblock.LOCK_NAME).exists()


def test_summarize_rename_leaves_no_lock(tmp_path, monkeypatch):
    # 2026-11-05 實跑：summarize 後資料夾改名，鎖檔跟著被搬走沒放掉
    from meeting_local import summarize
    monkeypatch.setattr(summarize, "_claude", lambda *a, **k: "# 測試標題\n\n## 一句話\n測試\n")
    job = tmp_path / "2026-11-05-1200"
    job.mkdir()
    (job / "transcript-by-minute.txt").write_text("[00:00] 測試\n", encoding="utf-8")
    (job / "entities.md").write_text("（無）\n", encoding="utf-8")
    assert cli.main(["summarize", str(job)]) == 0
    renamed = [p for p in tmp_path.iterdir() if p.is_dir()]
    assert [p.name for p in renamed] == ["2026-11-05-1200-測試標題"]
    assert not (renamed[0] / joblock.LOCK_NAME).exists()
