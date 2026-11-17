"""PyInstaller 的 macOS App 入口：不開終端機，直接啟動 Tk 視窗。

例外：第一個參數是 `mcp` 時，不開視窗，改當 MCP 伺服器（給使用者自己授權的 AI 助理讀會議記錄，見 mcp_server.py）。
"""
from __future__ import annotations

# PyInstaller 將這個入口檔當頂層模組執行，不能使用相對匯入；否則另一台
# Mac 啟動時會在建立 Tk 視窗前就拋出「no known parent package」。
import multiprocessing
import sys


if __name__ == "__main__":  # pragma: no cover - 由 PyInstaller 呼叫
    # 說話人分離在子程序跑（spawn）：封裝版的子程序也是這支執行檔，freeze_support 讓它認得自己是子程序、
    # 只跑分離不開視窗。少這行，子程序會再開一個視窗。
    multiprocessing.freeze_support()
    if len(sys.argv) > 1 and sys.argv[1] == "mcp":
        from meeting_local.mcp_server import main as mcp_main

        raise SystemExit(mcp_main())
    from meeting_local import webapp

    if webapp.available() and "--classic" not in sys.argv:
        raise SystemExit(webapp.main())
    from meeting_local.ui import main

    raise SystemExit(main())
