"""工作資料夾鎖：同一場會議同時只讓一個 meeting-local 程序處理。

2026-10-28：兩條線同時處理同一場（一邊修 bug、一邊重跑），只靠 ps 碰巧撞見；
第二支 whisper 只會報「port 已被占用（可能有上次殘留）」，看起來像殘留程序，容易被誤殺。
鎖檔讓第二支直接說出「誰、幾點起、在做哪一步」。

同一個 pid 可重複取鎖（all 串 transcribe→entities→summarize）；main() 結束時一律放掉
（UI 是長駐程序、在同程序裡呼叫 cli main，不能靠 atexit）。
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

LOCK_NAME = ".meeting-local.lock"
STALE_SECONDS = 12 * 3600  # 兩小時會議全流程約 30 分鐘；超過 12 小時的鎖一律當殘留

_held: set[Path] = set()


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def acquire(job: Path, step: str) -> None:
    lock = job / LOCK_NAME
    if lock.exists():
        try:
            info = json.loads(lock.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            info = {}
        pid = info.get("pid")
        fresh = time.time() - float(info.get("ts") or 0) < STALE_SECONDS
        if isinstance(pid, int) and pid != os.getpid() and fresh and _alive(pid):
            raise RuntimeError(
                f"這場正在被另一個 meeting-local 處理（pid {pid}，{info.get('started', '?')} 起，"
                f"步驟 {info.get('step', '?')}）。等它跑完再來；確定它已不在，就刪掉 {lock}"
            )
    lock.write_text(json.dumps({
        "pid": os.getpid(),
        "ts": time.time(),
        "started": time.strftime("%Y-%m-%d %H:%M:%S"),
        "step": step,
    }, ensure_ascii=False), encoding="utf-8")
    _held.add(lock)


def moved(old_job: Path, new_job: Path) -> None:
    """資料夾改名後呼叫：鎖檔跟著資料夾搬走了，放鎖要用新路徑。

    2026-11-05 實跑：summarize 後改名，release_all() 拿舊路徑讀不到、被 except 吞掉，
    改名後的資料夾裡留下一個看起來「還在跑」的鎖檔。
    """
    old_lock = old_job / LOCK_NAME
    if old_lock in _held:
        _held.discard(old_lock)
        _held.add(new_job / LOCK_NAME)


def release_all() -> None:
    for lock in list(_held):
        try:
            info = json.loads(lock.read_text(encoding="utf-8"))
            if info.get("pid") == os.getpid():
                lock.unlink()
        except (OSError, ValueError):
            pass
        _held.discard(lock)
