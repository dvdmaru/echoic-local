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
